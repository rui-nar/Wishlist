"""The media purge: image rows no gift needs, then their files once no kept
dump can reference them (gift images plan D9, D10).

A dump can point at a file only through an `images` row. A file is deleted
only when no row has existed for it since its orphan record's
`first_seen_at`, and that is earlier than the snapshot of every dump in the
backup directory (the horizon), so restoring any kept dump finds its files.
Every deletion of a row, and every run that saw the row, stamps the record
with `now`, so a record brought back by a restore cannot carry an older clock
past a live row (review R1-1).
"""

import logging
import os
import re
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.lists.models import Gift
from app.media.gift_images import stamp_orphan
from app.media.images import ATTACHABLE_FOR, GIFTS_DIR, TEMP_SUFFIX, VARIANTS
from app.media.models import Image, MediaOrphan

_log = logging.getLogger(__name__)

# A never-attached image's row goes this long after its upload: twice the
# time it can be attached, so the purge never races an attach (review R1-6).
RELEASE_PENDING_AFTER = 2 * ATTACHABLE_FOR
# A dump's snapshot is taken at most this long before its file date.
DUMP_DURATION = timedelta(days=1)
# A temporary file of `images.store` this old was left by a crash.
TEMPORARY_MAX_AGE = timedelta(days=1)
# The job (D10): first run 10 minutes after start, then every 24 h.
FIRST_RUN_DELAY = timedelta(minutes=10)
RUN_INTERVAL = timedelta(hours=24)

DUMP_SUFFIX = ".dump"
_DATE_IN_NAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# The two files of an image (D3); any other name is left alone.
_IMAGE_FILE = re.compile(
    "^([0-9a-f]{32})(?:"
    + "|".join(re.escape(suffix) for suffix in VARIANTS.values())
    + ")$"
)


class PurgeCounts(NamedTuple):
    horizon: datetime
    # Stems on disk with no image row, after the rows were released.
    orphans: int
    # Stems whose files were deleted.
    purged: int
    rows_released: int


def horizon(backup_dir: Path | None) -> datetime | None:
    """The snapshot time of the oldest kept dump, bounded from below (D9), or
    None when there is no dump to date: then nothing may be purged."""
    return _horizon(backup_dir)[0]


def _horizon(backup_dir: Path | None) -> tuple[datetime | None, str]:
    """The horizon, or None and the reason there is none."""
    if backup_dir is None:
        return None, "no backup directory"
    oldest: datetime | None = None
    try:
        with os.scandir(backup_dir) as entries:
            for entry in entries:
                if not entry.name.endswith(DUMP_SUFFIX):
                    continue
                try:
                    modified = entry.stat().st_mtime
                except FileNotFoundError:
                    continue  # rotated away while listing: no longer kept
                taken = datetime.fromtimestamp(modified, UTC)
                named = _date_in_name(entry.name)
                if named is not None:
                    taken = min(taken, named)
                oldest = taken if oldest is None else min(oldest, taken)
    except FileNotFoundError:
        return None, "backup directory missing"
    except OSError:
        # A dump that cannot be dated may be the oldest: no horizon.
        return None, "backup directory unreadable"
    if oldest is None:
        return None, "no dump"
    return oldest - DUMP_DURATION, ""


def _date_in_name(name: str) -> datetime | None:
    # wishlist_<YYYY-MM-DD>.dump, kept_<YYYY-MM-DD>.dump: 00:00 UTC that day.
    match = _DATE_IN_NAME.search(name)
    if match is None:
        return None
    try:
        return datetime(*(int(part) for part in match.groups()), tzinfo=UTC)
    except ValueError:
        return None  # not a date: the file date alone counts


def purge(
    db: Session, media_dir: Path, backup_dir: Path | None, now: datetime
) -> PurgeCounts | None:
    """One run of D9's steps 1 to 4, logged in one line.

    `db` is a session outside any transaction: the run commits as it goes, one
    transaction per step and one per purged stem. Returns None when skipped
    (no horizon, or the media directory cannot be listed): then nothing is
    changed at all.
    """
    found, reason = _horizon(backup_dir)
    gifts_dir = media_dir / GIFTS_DIR
    if found is not None:
        try:
            stems, temporary = _scan(gifts_dir)
        except OSError:
            found, reason = None, "media directory unreadable"
    if found is None:
        _log.warning("media purge: skipped (%s)", reason)
        return None
    # A dump dated in the future (a clock off on the host) must not let a
    # record stamped `now` be purged: no horizon later than a dump of now.
    limit = min(found, now - DUMP_DURATION)

    # Step 1: the stems that have a row now; then the rows no gift needs.
    with db.begin():
        had_row = {image_id.hex for image_id in db.scalars(select(Image.id))}
        released = db.scalars(
            delete(Image)
            .where(~exists().where(Gift.image_id == Image.id))
            .where(
                or_(
                    Image.attached_at.is_not(None),
                    Image.created_at < now - RELEASE_PENDING_AFTER,
                )
            )
            .returning(Image.id)
            .execution_options(synchronize_session=False)
        ).all()
        for image_id in released:
            stamp_orphan(db, image_id, now)

    # Step 2: live stems lose their record; orphans get one, reset to `now`
    # when the stem had a row at the start of the run (review R1-1).
    with db.begin():
        live = {image_id.hex for image_id in db.scalars(select(Image.id))}
        db.execute(
            delete(MediaOrphan).where(MediaOrphan.name.in_(sorted(stems & live)))
        )
        orphans = stems - live
        for name in sorted(orphans):
            statement = insert(MediaOrphan).values(name=name, first_seen_at=now)
            if name in had_row:
                statement = statement.on_conflict_do_update(
                    index_elements=[MediaOrphan.name],
                    set_={"first_seen_at": statement.excluded.first_seen_at},
                )
            else:
                statement = statement.on_conflict_do_nothing()
            db.execute(statement)

    # Step 3: the orphans first seen before the horizon.
    with db.begin():
        due = db.scalars(
            select(MediaOrphan.name).where(
                MediaOrphan.name.in_(sorted(orphans)), MediaOrphan.first_seen_at < limit
            )
        ).all()
    purged = sum(_purge_stem(db, gifts_dir, name, limit) for name in sorted(due))

    # Step 4: records of files gone, and temporary files left by a crash.
    with db.begin():
        db.execute(delete(MediaOrphan).where(MediaOrphan.name.not_in(sorted(stems))))
    for path, modified in temporary:
        if modified < now - TEMPORARY_MAX_AGE:
            path.unlink(missing_ok=True)

    counts = PurgeCounts(limit, len(orphans), purged, len(released))
    _log.info(
        "media purge: horizon=%s orphans=%d purged=%d rows_released=%d",
        counts.horizon.isoformat(),
        counts.orphans,
        counts.purged,
        counts.rows_released,
    )
    return counts


def _scan(gifts_dir: Path) -> tuple[set[str], list[tuple[Path, datetime]]]:
    """The image stems with a file under `gifts/`, and the temporary files of
    `images.store` with their modification times."""
    stems: set[str] = set()
    temporary: list[tuple[Path, datetime]] = []
    try:
        entries = list(os.scandir(gifts_dir))
    except FileNotFoundError:
        return stems, temporary  # nothing uploaded yet
    for entry in entries:
        if not entry.is_file(follow_symlinks=False):
            continue
        match = _IMAGE_FILE.match(entry.name)
        if match is not None:
            stems.add(match.group(1))
        elif entry.name.startswith(".") and entry.name.endswith(TEMP_SUFFIX):
            try:
                modified = entry.stat(follow_symlinks=False).st_mtime
            except FileNotFoundError:
                continue
            temporary.append((Path(entry.path), datetime.fromtimestamp(modified, UTC)))
    return stems, temporary


def _purge_stem(db: Session, gifts_dir: Path, name: str, limit: datetime) -> bool:
    """Deletes the stem's files, then its record, if the record is still due
    and no row has the stem, checked in the transaction holding the record."""
    with db.begin():
        first_seen_at = db.scalar(
            select(MediaOrphan.first_seen_at)
            .where(MediaOrphan.name == name)
            .with_for_update()
        )
        if first_seen_at is None or first_seen_at >= limit:
            return False  # gone or restamped since step 3 read it
        if db.scalar(select(exists().where(Image.id == uuid.UUID(hex=name)))):
            # A row came back (a restore): the files are live again.
            db.execute(delete(MediaOrphan).where(MediaOrphan.name == name))
            return False
        try:
            for suffix in VARIANTS.values():
                (gifts_dir / f"{name}{suffix}").unlink(missing_ok=True)
        except OSError as exc:
            # The record stays: the next run tries again.
            _log.warning("media purge: cannot delete %s (%s)", name, type(exc).__name__)
            return False
        db.execute(delete(MediaOrphan).where(MediaOrphan.name == name))
        return True


class MediaPurge:
    """The daily purge in a daemon thread of the app process (D10)."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        media_dir: Path,
        backup_dir: Path,
        clock: Callable[[], datetime],
        first_run_delay: timedelta = FIRST_RUN_DELAY,
    ) -> None:
        self._session_factory = session_factory
        self._media_dir = media_dir
        self._backup_dir = backup_dir
        self._clock = clock
        self._first_run_delay = first_run_delay
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="media-purge", daemon=True
        )

    def start(self) -> None:
        _make_visible()
        self._thread.start()

    def stop(self) -> None:
        """Returns once a run in progress has finished; waiting is cut short."""
        self._stop.set()
        self._thread.join()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        delay = self._first_run_delay
        while not self._stop.wait(delay.total_seconds()):
            try:
                with self._session_factory() as db:
                    purge(db, self._media_dir, self._backup_dir, self._clock())
            except Exception:
                # The next run tries again; a run that failed deleted nothing
                # it had not first committed as safe.
                _log.exception("media purge: failed")
            delay = RUN_INTERVAL


def _make_visible() -> None:
    # uvicorn configures its own loggers only, so without a handler of the
    # app's the run's INFO line would be dropped; the runbook greps for it.
    _log.setLevel(logging.INFO)
    if not _log.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        _log.addHandler(handler)
