"""The image pipeline: untrusted bytes in, two WebP files and a pending image
out (gift images plan D3, D4).

Only Pillow's JPEG, PNG, WebP and GIF decoders ever run, the pixel count is
checked from the header before anything is decoded, and the output is
re-encoded from pixels only, so nothing of the original's metadata (EXIF, GPS
included, XMP, ICC, comments) is ever written.
"""

import contextlib
import io
import logging
import os
import struct
import tempfile
import threading
import uuid
from pathlib import Path
from typing import NamedTuple

from PIL import Image as PILImage
from PIL import ImageCms, ImageOps
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.media.models import Image

_log = logging.getLogger(__name__)

# Limits (D4). Clients mirror MAX_BYTES to refuse a file before uploading it.
MAX_BYTES = 10 * 1024 * 1024
FORMATS = ("JPEG", "PNG", "WEBP", "GIF")
# Baseline JPEGs are decoded through draft(), at a fraction of their size.
MAX_JPEG_PIXELS = 100_000_000
# A progressive JPEG, or one whose components come in separate scans, makes
# libjpeg hold every DCT coefficient of the image, 2 bytes each, whatever
# draft() asks for (review R1-3): 8 MP at 3 components, about 48 MB.
MAX_BUFFERED_JPEG_COEFFICIENTS = 8_000_000 * 3
# Every other format is decoded whole: 64 MB for an RGBA image this size.
MAX_OTHER_PIXELS = 4096 * 4096
FULL_MAX_SIDE = 1600
THUMB_SIDE = 256
WEBP_QUALITY = 80
# One image decoded at a time; a request waiting longer gets image_busy.
LOCK_WAIT_SECONDS = 30.0

# Files (D3): <media_dir>/gifts/<id hex>.webp and <id hex>.thumb.webp, written
# under a temporary name ending in TEMP_SUFFIX, then renamed into place.
GIFTS_DIR = "gifts"
VARIANTS = {"full": ".webp", "thumb": ".thumb.webp"}
TEMP_SUFFIX = ".tmp"

# Pillow's own decompression-bomb check is replaced by the caps above, which
# are checked before decoding; its warning would fire on JPEGs the caps allow.
PILImage.MAX_IMAGE_PIXELS = None

DECODE_LOCK = threading.Lock()
_SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))

# Start-of-frame markers. 0xC4 (DHT), 0xC8 (reserved) and 0xCC (DAC) share
# the range but are not frames.
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_PROGRESSIVE_SOF_MARKERS = frozenset({0xC2, 0xC6, 0xCA, 0xCE})
_SOS = 0xDA
# Markers with no length field: TEM, RST0-7, SOI.
_STANDALONE_MARKERS = frozenset({0x01, *range(0xD0, 0xD9)})


class ImageRejected(Exception):
    """An image the pipeline refuses; `code` is the client's error code (D11)."""

    status_code = 422
    code = ""


class ImageTooLarge(ImageRejected):
    status_code = 413
    code = "image_too_large"


class ImageUnsupported(ImageRejected):
    code = "image_unsupported"


class ImageTooManyPixels(ImageRejected):
    code = "image_too_many_pixels"


class ImageBusy(ImageRejected):
    status_code = 503
    code = "image_busy"


class Processed(NamedTuple):
    full: bytes
    thumb: bytes
    # Of the full version.
    width: int
    height: int


def process(data: bytes) -> Processed:
    """The full and thumbnail WebP of an image, per D4.

    Raises an `ImageRejected` for anything refused. Holds DECODE_LOCK while
    it works, so the process decodes one image at a time.
    """
    if len(data) > MAX_BYTES:
        raise ImageTooLarge()
    if not DECODE_LOCK.acquire(timeout=LOCK_WAIT_SECONDS):
        raise ImageBusy()
    try:
        with PILImage.open(io.BytesIO(data), formats=FORMATS) as source:
            return _process(source, data)
    except ImageRejected:
        raise
    # A malformed or hostile file: what a decoder raises on bad input.
    except OSError, ValueError, SyntaxError, EOFError, IndexError, struct.error:
        raise ImageUnsupported() from None
    finally:
        DECODE_LOCK.release()


def _process(source: PILImage.Image, data: bytes) -> Processed:
    width, height = source.size
    if source.format in ("JPEG", "MPO"):
        components, buffered = _jpeg_frame(data)
        if width * height > MAX_JPEG_PIXELS or (
            buffered and width * height * components > MAX_BUFFERED_JPEG_COEFFICIENTS
        ):
            raise ImageTooManyPixels()
        if max(width, height) > FULL_MAX_SIDE:
            # The smallest scale (1/2, 1/4, 1/8) still at least FULL_MAX_SIDE
            # on the longest side.
            source.draft(None, _fitted(width, height, FULL_MAX_SIDE))
    elif width * height > MAX_OTHER_PIXELS:
        raise ImageTooManyPixels()

    # Decodes; a GIF or an animated WebP decodes its first frame only.
    source.load()
    info = dict(source.info)
    # Reduce first, then everything else on the reduced image (review R1-4).
    # Each full-size image is released as soon as the next one exists.
    image = _working_mode(source)
    if image is not source:
        source.close()
    image = _box_reduced(image, FULL_MAX_SIDE)
    if image is not source:
        source.close()
    image = _resized(image, FULL_MAX_SIDE)
    # The orientation and the profile are in the original's metadata.
    image.info = info
    ImageOps.exif_transpose(image, in_place=True)
    image = _to_srgb(image, info.get("icc_profile"))
    # Nothing of the original goes out: the encoders get the pixels only.
    image.info = {}
    thumb = ImageOps.fit(
        image, (THUMB_SIDE, THUMB_SIDE), method=PILImage.Resampling.LANCZOS
    )
    return Processed(
        full=_webp(image), thumb=_webp(thumb), width=image.width, height=image.height
    )


def _jpeg_frame(data: bytes) -> tuple[int, bool]:
    """The JPEG's component count, and whether libjpeg buffers it whole.

    Read from the markers before the first scan, without decoding. Buffered:
    a progressive frame, or a first scan holding fewer components than the
    frame (the components come in separate scans), both of which make libjpeg
    keep the whole image's coefficients, whatever draft() asks for.
    """
    position = 2  # after SOI
    components = 0
    progressive = False
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            # Junk between segments, which Pillow skips too.
            position += 1
            continue
        marker = data[position + 1]
        if marker == 0xFF:
            # Fill byte.
            position += 1
            continue
        if marker in _STANDALONE_MARKERS or marker == 0x00:
            position += 2
            continue
        (length,) = struct.unpack(">H", data[position + 2 : position + 4])
        segment = data[position + 4 : position + 2 + length]
        if marker in _SOF_MARKERS and len(segment) >= 6:
            components = segment[5]
            progressive = marker in _PROGRESSIVE_SOF_MARKERS
        elif marker == _SOS and components and segment:
            return components, progressive or segment[0] < components
        position += 2 + length
    # No frame, or no scan after it: nothing a decoder could show.
    raise ImageUnsupported()


def _fitted(width: int, height: int, side: int) -> tuple[int, int]:
    """The size with the same proportions whose longest side is `side`."""
    if width >= height:
        return side, max(1, -(-height * side // width))
    return max(1, -(-width * side // height)), side


def _working_mode(image: PILImage.Image) -> PILImage.Image:
    """The image in L, LA, RGB, RGBA or CMYK, transparency kept as alpha."""
    transparent = "transparency" in image.info
    if image.mode in ("L", "LA", "RGB", "RGBA", "CMYK") and not transparent:
        return image
    alpha = transparent or image.mode in ("LA", "PA", "RGBA")
    grey = image.mode in ("1", "L", "LA", "F") or image.mode.startswith("I")
    return image.convert(
        ("LA" if alpha else "L") if grey else ("RGBA" if alpha else "RGB")
    )


_PREMULTIPLIED = {"RGBA": "RGBa", "LA": "La"}
_STRAIGHT = {"RGBa": "RGBA", "La": "LA"}


def _box_reduced(image: PILImage.Image, side: int) -> PILImage.Image:
    """An image larger than `side` reduced by the largest integer factor that
    keeps its longest side at least `side`, alpha premultiplied.

    Runs in strips: Pillow premultiplies alpha by converting the whole image,
    which for a 4096 x 4096 RGBA image is another 64 MB next to the decode
    (review R1-4); a strip's copy is a few MB. A smaller image is returned
    as it is.
    """
    if max(image.size) <= side:
        return image
    factor = max(image.size) // side
    mode = _PREMULTIPLIED.get(image.mode, image.mode)
    if factor == 1:
        # Under 2 x `side`: no reduction, only the premultiplied copy.
        return image.convert(mode) if mode != image.mode else image
    width, height = image.size
    # A multiple of the factor, so the strips reduce exactly as the whole.
    step = factor * 64
    reduced = PILImage.new(mode, (-(-width // factor), -(-height // factor)))
    for top in range(0, height, step):
        strip = image.crop((0, top, width, min(top + step, height)))
        if strip.mode != mode:
            strip = strip.convert(mode)
        reduced.paste(strip.reduce(factor), (0, top // factor))
    return reduced


def _resized(image: PILImage.Image, side: int) -> PILImage.Image:
    """The image with its longest side at most `side`, never upscaled, alpha
    straight again."""
    if max(image.size) > side:
        image = image.resize(_fitted(*image.size, side), PILImage.Resampling.LANCZOS)
    if image.mode in _STRAIGHT:
        image = image.convert(_STRAIGHT[image.mode])
    return image


def _to_srgb(image: PILImage.Image, icc_profile: bytes | None) -> PILImage.Image:
    """The image in RGB or RGBA, its colours converted to sRGB by its profile.

    A profile lcms2 cannot use is refused (review R1-2): logged with its size
    only, never its content or the image's.
    """
    alpha = image.getchannel("A") if image.mode in ("LA", "RGBA") else None
    colour = image.convert(image.mode[:-1]) if alpha is not None else image
    if icc_profile:
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
            colour = ImageCms.profileToProfile(colour, profile, _SRGB, outputMode="RGB")
        except ImageCms.PyCMSError, OSError, ValueError, TypeError:
            _log.warning("image icc: failed size=%d", len(icc_profile))
            raise ImageUnsupported() from None
        assert colour is not None
    elif colour.mode != "RGB":
        colour = colour.convert("RGB")
    if alpha is not None:
        colour.putalpha(alpha)
    return colour


def _webp(image: PILImage.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=WEBP_QUALITY)
    return buffer.getvalue()


def image_path(media_dir: Path, image_id: uuid.UUID, variant: str) -> Path:
    return media_dir / GIFTS_DIR / f"{image_id.hex}{VARIANTS[variant]}"


def store(media_dir: Path, image_id: uuid.UUID, full: bytes, thumb: bytes) -> None:
    """Writes both files under their final names, each complete or absent.

    A file is never modified afterwards (D3): VAL's media are hard links to
    PROD's.
    """
    (media_dir / GIFTS_DIR).mkdir(parents=True, exist_ok=True)
    for variant, content in (("full", full), ("thumb", thumb)):
        path = image_path(media_dir, image_id, variant)
        fd, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=TEMP_SUFFIX
        )
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise


def ingest(db: Session, media_dir: Path, user: User, data: bytes) -> Image:
    """A new pending image of `user` from untrusted bytes (D1).

    The files are written before the row: a row never points at files that do
    not exist, and files left without a row by a failed transaction are
    orphans the purge removes (D9).
    """
    processed = process(data)
    image = Image(
        id=uuid.uuid4(),
        uploaded_by=user.id,
        width=processed.width,
        height=processed.height,
    )
    store(media_dir, image.id, processed.full, processed.thumb)
    db.add(image)
    db.flush()
    return image
