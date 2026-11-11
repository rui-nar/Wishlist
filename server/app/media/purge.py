"""The media purge: image rows no gift needs, then their files once no kept
dump can reference them (gift images plan D9, D10).

A dump can point at a file only through an `images` row. A file is deleted
only when no row has existed for it since its orphan record's
`first_seen_at`, and that is earlier than the snapshot of every dump in the
backup directory (the horizon), so restoring any kept dump finds its files.
Every deletion of a row, and every run that saw the row, stamps the record
with `now`, so a record brought back by a restore cannot carry an older clock
past a live row (review R1-1).

The records live in the database, so a rollback to an older dump can bring
back a record older than a row that existed since (review R5-1). The files
remember too: every run sets the modification time of a live row's files to
`now`, and a stem goes only when its record and its files are both older
than the horizon.

The same thread measures the images uploaded before `images.bytes` existed
(admin panel plan D7). That reads sizes only, so it runs on every run, with or
without a horizon (review R1-4).
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

from sqlalchemy import delete, exists, func, or_, select, update
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
# Image rows measured per transaction (admin panel plan D7).
SIZES_BATCH = 200

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


class SizeCounts(NamedTuple):
    filled: int
    # Rows left unmeasured: a file missing or unreadable.
    skipped: int


def horizon(backup_dir: Path | None) -> datetime | None:
    """The snapshot time of the oldest kept dump, bounded from below (D9), or
    None when there is no dump to date: then nothing may be purged."""
    return _horizon(backup_dir)[0]


def _horizon(
    backup_dir: Path | None,
) -> tuple[datetime | None, datetime | None, str]:
    """The horizon and the latest date read from a dump (its file date or the
    date in its name), or None, None and the reason there is no horizon."""
    if backup_dir is None:
        return None, None, "no backup directory"
    oldest: datetime | None = None
    latest: datetime | None = None
    try:
        with os.scandir(backup_dir) as entries:
            for entry in entries:
                if not entry.name.endswith(DUMP_SUFFIX):
                    continue
                try:
                    modified = entry.stat().st_mtime
                except FileNotFoundError:
                    continue  # rotated away while listing: no longer kept
                dates = [datetime.fromtimestamp(modified, UTC)]
                named = _date_in_name(entry.name)
                if named is not None:
                    dates.append(named)
                oldest = min(dates if oldest is None else [oldest, *dates])
                latest = max(dates if latest is None else [latest, *dates])
    except FileNotFoundError:
        return None, None, "backup directory missing"
    except OSError:
        # A dump that cannot be dated may be the oldest: no horizon.
        return None, None, "backup directory unreadable"
    if oldest is None:
        return None, None, "no dump"
    return oldest - DUMP_DURATION, latest, ""


def _date_in_name(name: str) -> datetime | None:
    # shushgift_<YYYY-MM-DD>.dump, kept_<YYYY-MM-DD>.dump: 00:00 UTC that day.
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
    (no horizon, the media directory cannot be listed, or the clock is behind
    a date already recorded): then nothing is changed at all.
    """
    limit, latest_dump, reason = _horizon(backup_dir)
    gifts_dir = media_dir / GIFTS_DIR
    if limit is not None:
        try:
            stems, temporary = _scan(gifts_dir)
        except OSError:
            limit, reason = None, "media directory unreadable"
    if limit is not None and _clock_behind(db, latest_dump, now):
        # A clock gone backwards would stamp records and files older than
        # what they replace, and the horizon could pass them early (R5-2).
        limit, reason = None, "clock behind"
    if limit is None:
        _log.warning("media purge: skipped (%s)", reason)
        return None

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
        # The memory a database restore cannot take back (review R5-1).
        for name in sorted(stems & live):
            _touch(gifts_dir, name, now)
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


def fill_sizes(db: Session, media_dir: Path) -> SizeCounts:
    """Sets `bytes` on every image row that has none, to the size of its two
    files (admin panel plan D7). Reads sizes only and deletes nothing.

    `db` is a session outside any transaction: one transaction per batch of
    SIZES_BATCH rows. A row another transaction holds is skipped, never waited
    for, so this never deadlocks with an account's deletion. A row whose
    files are not both readable stays null, and the next run tries again.
    Logged in one line when there was anything to measure.
    """
    gifts_dir = media_dir / GIFTS_DIR
    filled = skipped = 0
    after: uuid.UUID | None = None
    while True:
        with db.begin():
            query = (
                select(Image.id)
                .where(Image.bytes.is_(None))
                .order_by(Image.id)
                .limit(SIZES_BATCH)
                # FOR NO KEY UPDATE SKIP LOCKED: this never waits, and the
                # foreign-key checks on `gifts.image_id` (FOR KEY SHARE) do not
                # wait on it. An attach's FOR UPDATE or an account deletion's
                # SET NULL on `uploaded_by` can wait for one batch, never more.
                .with_for_update(key_share=True, skip_locked=True)
            )
            if after is not None:
                query = query.where(Image.id > after)
            batch = db.scalars(query).all()
            for image_id in batch:
                size = _files_size(gifts_dir, image_id.hex)
                if size is None:
                    skipped += 1
                    continue
                db.execute(
                    update(Image)
                    .where(Image.id == image_id)
                    .values(bytes=size)
                    .execution_options(synchronize_session=False)
                )
                filled += 1
        if len(batch) < SIZES_BATCH:
            break
        after = batch[-1]
    counts = SizeCounts(filled, skipped)
    if filled or skipped:
        _log.info("media sizes: filled=%d skipped=%d", filled, skipped)
    return counts


def _files_size(gifts_dir: Path, name: str) -> int | None:
    """The size of the stem's two files, None unless both can be read."""
    total = 0
    for suffix in VARIANTS.values():
        try:
            total += (gifts_dir / f"{name}{suffix}").stat().st_size
        except FileNotFoundError:
            return None
        except OSError as exc:
            _log.warning(
                "media sizes: cannot measure %s (%s)", name, type(exc).__name__
            )
            return None
    return total


def _clock_behind(db: Session, latest_dump: datetime | None, now: datetime) -> bool:
    """Whether a date already recorded, in the database or by a dump, is later
    than `now` (review R5-2)."""
    with db.begin():
        latest_record = db.scalar(select(func.max(MediaOrphan.first_seen_at)))
        latest_upload = db.scalar(select(func.max(Image.created_at)))
    return any(
        recorded is not None and recorded > now
        for recorded in (latest_dump, latest_record, latest_upload)
    )


def _touch(gifts_dir: Path, name: str, now: datetime) -> None:
    for suffix in VARIANTS.values():
        try:
            os.utime(gifts_dir / f"{name}{suffix}", (now.timestamp(),) * 2)
        except FileNotFoundError:
            continue
        except OSError as exc:
            _log.warning("media purge: cannot touch %s (%s)", name, type(exc).__name__)


def _files_modified(gifts_dir: Path, name: str) -> datetime | None:
    """The latest modification time of the stem's files, None if none is
    there."""
    times = []
    for suffix in VARIANTS.values():
        try:
            times.append((gifts_dir / f"{name}{suffix}").stat().st_mtime)
        except FileNotFoundError:
            continue
    return datetime.fromtimestamp(max(times), UTC) if times else None


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
    """Deletes the stem's files, then its record, if the record and the files
    are still older than the horizon and no row has the stem, checked in the
    transaction holding the record."""
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
        modified = _files_modified(gifts_dir, name)
        if modified is not None and modified >= limit:
            # A row had the files after the record was written: a rollback
            # brought back an older record (review R5-1).
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
    """The daily media job in a daemon thread of the app process (D10): the
    purge, where dumps can be dated, then `fill_sizes`, everywhere (admin
    panel plan D7, review R1-4)."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        media_dir: Path,
        # None: no dump can be dated, and the purge does not run (DEV, VAL).
        backup_dir: Path | None,
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
            if self._backup_dir is not None:
                try:
                    with self._session_factory() as db:
                        purge(db, self._media_dir, self._backup_dir, self._clock())
                except Exception:
                    # The next run tries again; a run that failed deleted
                    # nothing it had not first committed as safe.
                    _log.exception("media purge: failed")
            # Whatever the purge did: it only reads sizes (review R1-4).
            try:
                with self._session_factory() as db:
                    fill_sizes(db, self._media_dir)
            except Exception:
                _log.exception("media sizes: failed")
            delay = RUN_INTERVAL


def _make_visible() -> None:
    # uvicorn configures its own loggers only, so without a handler of the
    # app's the run's INFO line would be dropped; the runbook greps for it.
    _log.setLevel(logging.INFO)
    if not _log.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        _log.addHandler(handler)
