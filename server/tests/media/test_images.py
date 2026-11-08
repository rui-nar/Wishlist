"""The image pipeline (gift images plan D4), on images generated here."""

import io
import logging
import struct
import subprocess
import sys
import textwrap
import zlib
from pathlib import Path

import pytest
from PIL import ExifTags, Image, ImageCms

from app.media import images
from app.media.images import (
    ImageTooManyPixels,
    ImageUnsupported,
    process,
)

SERVER_DIR = Path(__file__).resolve().parents[2]
SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def encoded(image: Image.Image, format: str, **params) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format, **params)
    return buffer.getvalue()


def gradient(mode: str, size: tuple[int, int]) -> Image.Image:
    """A smooth image: compresses well, so even a large one stays small."""
    band = Image.linear_gradient("L").resize(size)
    flipped = band.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return Image.merge(mode, [band, flipped, band, flipped][: len(mode)])


def opened(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def png_header(width: int, height: int) -> bytes:
    """A PNG declaring this size, whose pixel data is junk: decoding it fails."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload)
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", b"junk, not zlib")
        + chunk(b"IEND", b"")
    )


def jpeg_header(width: int, height: int, sof: int, scan_components: int) -> bytes:
    """A JPEG frame of three components and the start of its first scan,
    followed by junk instead of entropy-coded data: decoding it fails."""
    frame = (
        struct.pack(">BHHB", 8, height, width, 3)
        + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    scan = (
        bytes([scan_components])
        + b"".join(bytes([index + 1, 0x00]) for index in range(scan_components))
        + b"\x00\x3f\x00"
    )
    return (
        b"\xff\xd8"
        + bytes([0xFF, sof])
        + struct.pack(">H", len(frame) + 2)
        + frame
        + b"\xff\xda"
        + struct.pack(">H", len(scan) + 2)
        + scan
        + b"junk" * 16
        + b"\xff\xd9"
    )


@pytest.mark.parametrize(
    ("format", "mode"),
    [("JPEG", "RGB"), ("PNG", "RGBA"), ("WEBP", "RGB"), ("GIF", "P")],
)
def test_each_format_gives_a_full_webp_and_a_square_thumbnail(format, mode):
    source = gradient("RGB", (2000, 1000))
    if mode != "RGB":
        source = source.convert(mode)

    result = process(encoded(source, format))

    full, thumb = opened(result.full), opened(result.thumb)
    assert (full.format, thumb.format) == ("WEBP", "WEBP")
    assert full.size == (1600, 800) == (result.width, result.height)
    assert thumb.size == (256, 256)


def test_a_small_image_is_not_upscaled():
    result = process(encoded(gradient("RGB", (300, 200)), "PNG"))

    assert opened(result.full).size == (300, 200)
    assert (result.width, result.height) == (300, 200)
    assert opened(result.thumb).size == (256, 256)


def test_a_tall_image_keeps_its_proportions():
    result = process(encoded(gradient("RGB", (900, 3600)), "PNG"))

    assert (result.width, result.height) == (400, 1600)


def test_the_exif_orientation_is_applied():
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6  # rotate 90 degrees clockwise to view

    result = process(encoded(gradient("RGB", (300, 200)), "JPEG", exif=exif))

    assert (result.width, result.height) == (200, 300)
    assert opened(result.full).size == (200, 300)


def test_no_metadata_survives():
    exif = Image.Exif()
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (48.0, 51.0, 24.0)
    exif[ExifTags.Base.Make] = "Phone"
    jpeg = encoded(gradient("RGB", (300, 200)), "JPEG", exif=exif)
    assert opened(jpeg).getexif().get_ifd(ExifTags.IFD.GPSInfo)
    png = encoded(gradient("RGB", (300, 200)), "PNG", icc_profile=SRGB_PROFILE)
    assert opened(png).info["icc_profile"]

    for source in (jpeg, png):
        result = process(source)
        for output in (result.full, result.thumb):
            info = opened(output).info
            assert not {"exif", "xmp", "icc_profile"} & info.keys(), info
            assert not opened(output).getexif()


def test_transparency_is_kept():
    source = gradient("RGBA", (400, 300))
    source.putalpha(0)
    source.paste((200, 30, 30, 255), (100, 100, 300, 200))

    result = process(encoded(source, "PNG"))

    full = opened(result.full)
    assert full.mode == "RGBA"
    assert full.getpixel((10, 10))[3] == 0
    assert full.getpixel((200, 150))[3] == 255
    assert opened(result.thumb).mode == "RGBA"


def test_a_gif_palette_transparency_is_kept():
    source = Image.new("P", (100, 100), 1)
    source.putpalette([0, 0, 0, 255, 0, 0])
    source.paste(0, (0, 0, 50, 100))

    result = process(encoded(source, "GIF", transparency=0))

    full = opened(result.full).convert("RGBA")
    assert full.getpixel((10, 50))[3] == 0
    red, green, blue, alpha = full.getpixel((90, 50))
    # Within WebP's lossy encoding.
    assert (red, alpha) == (255, 255) and green < 5 and blue < 5


def test_an_animated_gif_gives_its_first_frame():
    frames = [Image.new("RGB", (50, 50), colour) for colour in ("red", "blue")]

    result = process(encoded(frames[0], "GIF", save_all=True, append_images=frames[1:]))

    red, green, blue = opened(result.full).convert("RGB").getpixel((25, 25))
    assert red > 200 and blue < 50


def test_an_srgb_profile_goes_through_the_conversion_unchanged():
    source = Image.new("RGB", (300, 200), (200, 120, 40))

    result = process(encoded(source, "PNG", icc_profile=SRGB_PROFILE))

    full = opened(result.full)
    assert full.mode == "RGB"
    # Within WebP's lossy encoding of a flat colour.
    pixel = full.getpixel((150, 100))
    assert all(abs(a - b) <= 4 for a, b in zip(pixel, (200, 120, 40), strict=True))


@pytest.mark.parametrize(
    "data",
    [
        b"just some text",
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>',
        # The start of a HEIC file: its ftyp box.
        b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64,
        # Formats Pillow could decode but the pipeline does not allow.
        encoded(Image.new("RGB", (10, 10)), "BMP"),
        encoded(Image.new("RGB", (10, 10)), "TIFF"),
        # A truncated PNG.
        encoded(gradient("RGB", (300, 200)), "PNG")[:200],
    ],
    ids=["text", "svg", "heic", "bmp", "tiff", "truncated"],
)
def test_anything_else_is_unsupported(data):
    with pytest.raises(ImageUnsupported):
        process(data)


def test_a_huge_png_is_refused_from_its_header():
    # The IDAT is junk: decoding it would fail as unsupported, not refused.
    with pytest.raises(ImageTooManyPixels):
        process(png_header(20000, 20000))


def test_a_png_at_the_cap_is_not_refused_for_its_pixels():
    # Exactly 4096 x 4096 passes the check, then fails on its junk pixels.
    with pytest.raises(ImageUnsupported):
        process(png_header(4096, 4096))
    with pytest.raises(ImageTooManyPixels):
        process(png_header(4097, 4096))


@pytest.mark.parametrize(
    ("width", "height"), [(20000, 20000), (3000, 2667)], ids=["huge", "just-over-8MP"]
)
def test_a_large_progressive_jpeg_is_refused_from_its_header(width, height):
    with pytest.raises(ImageTooManyPixels):
        process(jpeg_header(width, height, sof=0xC2, scan_components=3))


def test_a_large_multi_scan_baseline_jpeg_is_refused_from_its_header():
    # Components in separate scans: libjpeg buffers the whole image too.
    with pytest.raises(ImageTooManyPixels):
        process(jpeg_header(3000, 2667, sof=0xC0, scan_components=1))


def test_a_baseline_jpeg_header_over_8mp_passes_the_check():
    # One interleaved scan: decoded through draft(), so up to 100 MP. The junk
    # scan then fails to decode.
    with pytest.raises(ImageUnsupported):
        process(jpeg_header(3000, 2667, sof=0xC0, scan_components=3))
    with pytest.raises(ImageTooManyPixels):
        process(jpeg_header(10001, 10000, sof=0xC0, scan_components=3))


def test_a_progressive_jpeg_under_8mp_is_accepted():
    source = encoded(gradient("RGB", (3000, 2000)), "JPEG", progressive=True)
    assert opened(source).info.get("progressive")

    result = process(source)

    assert (result.width, result.height) == (1600, 1067)


def test_a_large_baseline_jpeg_is_decoded_reduced():
    source = encoded(gradient("RGB", (6400, 1600)), "JPEG")

    result = process(source)

    assert (result.width, result.height) == (1600, 400)


def test_a_malformed_icc_profile_is_unsupported_and_logged(caplog):
    profile = b"not an ICC profile " * 10
    source = encoded(gradient("RGB", (300, 200)), "PNG", icc_profile=profile)

    with caplog.at_level(logging.WARNING, logger="app.media.images"):
        with pytest.raises(ImageUnsupported):
            process(source)

    assert [record.getMessage() for record in caplog.records] == [
        f"image icc: failed size={len(profile)}"
    ]


def test_the_strip_reduction_equals_a_whole_reduction():
    # Height not a multiple of the strip, transparent edges: premultiplied
    # alpha must give exactly what Pillow's own reduction gives.
    source = gradient("RGBA", (3300, 1000))
    source.paste((255, 255, 255, 0), (0, 0, 3300, 300))

    reduced = images._box_reduced(source, 1600)

    assert reduced.mode == "RGBa"
    assert reduced.tobytes() == source.convert("RGBa").reduce(2).tobytes()


def test_too_large_bytes_are_refused():
    with pytest.raises(images.ImageTooLarge):
        process(b"\x00" * (images.MAX_BYTES + 1))


MEMORY_SCRIPT = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    from app.media.images import process


    def status(field):
        with open("/proc/self/status") as file:
            for line in file:
                if line.startswith(field + ":"):
                    return int(line.split()[1])


    data = Path(sys.argv[1]).read_bytes()
    baseline = status("VmRSS")
    # Resets the peak to the current RSS (VmHWM).
    with open("/proc/self/clear_refs", "w") as file:
        file.write("5")
    process(data)
    print(status("VmHWM") - baseline)
    """
)


@pytest.mark.skipif(
    not Path("/proc/self/clear_refs").exists(), reason="needs Linux's /proc"
)
@pytest.mark.parametrize(
    ("mode", "params"),
    [("RGB", {"icc_profile": SRGB_PROFILE}), ("RGBA", {})],
    ids=["rgb-icc", "rgba"],
)
def test_peak_memory_of_a_4096_png_stays_under_100mb(tmp_path, mode, params):
    """Review R1-4. Peak RSS, not tracemalloc: Pillow allocates pixels outside
    Python's allocator. Read from /proc, not ru_maxrss, which a child process
    inherits from its parent across exec: this test process, holding a large
    image, would set the child's baseline above its real peak. In a
    subprocess, so nothing else this process did counts."""
    path = tmp_path / "large.png"
    path.write_bytes(encoded(gradient(mode, (4096, 4096)), "PNG", **params))
    assert path.stat().st_size <= images.MAX_BYTES

    run = subprocess.run(
        [sys.executable, "-c", MEMORY_SCRIPT, str(path)],
        cwd=SERVER_DIR,
        capture_output=True,
        text=True,
    )

    assert run.returncode == 0, run.stderr
    rise = int(run.stdout)  # kB
    # The decode alone is 64 MB: a smaller rise means the measure is broken.
    assert 60 * 1024 < rise < 100 * 1024, f"peak rose by {rise} kB"
