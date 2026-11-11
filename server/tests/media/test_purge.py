"""The media purge (gift images plan D9, D10): image rows no gift needs are
released, and files go only once no kept dump can reference them.

Dumps are empty files dated with `os.utime`; images are rows written directly
with two small files, so each case sets exactly the state it needs.
"""

import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.lists.models import Gift, List
from app.main import create_app
from app.media.images import image_path
from app.media.models import Image, MediaOrphan
from app.media.purge import MediaPurge, SizeCounts, fill_sizes, horizon, purge
from app.settings import Settings

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)
DAY = timedelta(days=1)


@pytest.fixture
def media_dir(tmp_path):
    return tmp_path / "media"


@pytest.fixture
def backups(tmp_path):
    path = tmp_path / "backups"
    path.mkdir()
    return path


@pytest.fixture
def db(engine, empty_tables):
    return engine


def dump(backups, name, at):
    path = backups / name
    path.write_bytes(b"")
    os.utime(path, (at.timestamp(), at.timestamp()))
    return path


def nightly(backups, oldest, count=30, every=DAY):
    """`count` nightly dumps, the oldest of `oldest`'s day, each written at
    03:00 UTC of the day in its name, as backup.sh does."""
    for n in range(count):
        day = (oldest + n * every).date()
        written = datetime(day.year, day.month, day.day, 3, tzinfo=UTC)
        dump(backups, f"shushgift_{day.isoformat()}.dump", written)


def recent_dumps(backups, after):
    """Replaces every dump with nightly ones all taken more than a day after
    `after`: the horizon has passed it."""
    for path in backups.glob("*.dump"):
        path.unlink()
    nightly(backups, after + 2 * DAY, count=3)


def write_files(media_dir, image_id, written):
    """The image's two files, as `images.store` wrote them at `written`."""
    for variant in ("full", "thumb"):
        path = image_path(media_dir, image_id, variant)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"webp")
        os.utime(path, (written.timestamp(),) * 2)


def modified(media_dir, image_id):
    return {
        datetime.fromtimestamp(image_path(media_dir, image_id, v).stat().st_mtime, UTC)
        for v in ("full", "thumb")
    }


def has_files(media_dir, image_id):
    found = [image_path(media_dir, image_id, v).exists() for v in ("full", "thumb")]
    assert found[0] == found[1]
    return found[0]


def add_image(
    engine, media_dir, *, created_at=NOW, attached_at=None, on_gift=False, files=True
):
    image_id = uuid.uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            Image(
                id=image_id,
                width=10,
                height=10,
                created_at=created_at,
                attached_at=attached_at,
            )
        )
        if on_gift:
            listing = List(title="Birthday", recipient_kind="self")
            session.add(listing)
            session.flush()
            session.add(
                Gift(
                    list_id=listing.id,
                    title="Kite",
                    description="",
                    links=[],
                    image_id=image_id,
                )
            )
    if files:
        write_files(media_dir, image_id, created_at)
    return image_id


def orphan_files(media_dir, written=NOW - 365 * DAY):
    """Files with no row, as a failed upload leaves them."""
    image_id = uuid.uuid4()
    write_files(media_dir, image_id, written)
    return image_id


def has_row(engine, image_id):
    with Session(engine) as session:
        return session.get(Image, image_id) is not None


def first_seen(engine, image_id):
    with Session(engine) as session:
        return session.scalar(
            select(MediaOrphan.first_seen_at).where(MediaOrphan.name == image_id.hex)
        )


def set_first_seen(engine, image_id, at):
    with Session(engine) as session, session.begin():
        session.merge(MediaOrphan(name=image_id.hex, first_seen_at=at))


def after_step_1(session, callback):
    """Calls `callback` once, when the transaction releasing rows (step 1)
    has committed in `session`."""
    released = []

    @event.listens_for(session, "do_orm_execute")
    def note(state):
        if state.is_delete and state.statement.table.name == "images":
            released.append(True)

    @event.listens_for(session, "after_commit")
    def call(_session):
        if released and released.pop():
            callback()


def run(engine, media_dir, backups, now=NOW, session=None):
    with session or Session(engine) as db:
        return purge(db, media_dir, backups, now)


# The horizon.


def test_horizon_is_the_oldest_dump_minus_a_day(backups):
    nightly(backups, NOW - 30 * DAY)

    # The oldest is shushgift_2026-10-09.dump, written that day at 03:00.
    assert horizon(backups) == datetime(2026, 10, 8, tzinfo=UTC)


def test_horizon_takes_the_earlier_of_the_file_date_and_the_name(backups):
    dump(backups, "shushgift_2026-11-01.dump", NOW)
    dump(backups, "before-restore.dump", datetime(2026, 11, 3, 9, tzinfo=UTC))

    assert horizon(backups) == datetime(2026, 10, 31, tzinfo=UTC)


def test_horizon_ignores_other_names_and_a_date_that_is_not_one(backups):
    dump(backups, "shushgift_2026-11-05.dump", datetime(2026, 11, 5, 3, tzinfo=UTC))
    dump(backups, ".shushgift_2020-01-01.dump.partial", NOW - 900 * DAY)
    dump(backups, "notes.txt", NOW - 900 * DAY)
    dump(backups, "kept_2026-13-45.dump", datetime(2026, 11, 6, tzinfo=UTC))

    assert horizon(backups) == datetime(2026, 11, 4, tzinfo=UTC)


def test_no_horizon_without_a_dump(tmp_path, backups):
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("")

    assert horizon(None) is None
    assert horizon(tmp_path / "missing") is None
    assert horizon(not_a_directory) is None
    assert horizon(backups) is None


# Files and records.


def test_a_referenced_file_is_never_deleted(db, media_dir, backups):
    image_id = add_image(db, media_dir, attached_at=NOW - 90 * DAY, on_gift=True)
    set_first_seen(db, image_id, NOW - 90 * DAY)  # a stale record
    recent_dumps(backups, NOW - 90 * DAY)

    counts = run(db, media_dir, backups)

    assert has_row(db, image_id) and has_files(media_dir, image_id)
    assert first_seen(db, image_id) is None
    assert counts.purged == 0 and counts.rows_released == 0
    # The run's memory a database rollback cannot take back (review R5-1).
    assert modified(media_dir, image_id) == {NOW}


def test_a_new_orphan_is_recorded_not_deleted(db, media_dir, backups):
    nightly(backups, NOW - 30 * DAY)
    image_id = orphan_files(media_dir)

    counts = run(db, media_dir, backups)

    assert first_seen(db, image_id) == NOW
    assert has_files(media_dir, image_id)
    assert counts.orphans == 1 and counts.purged == 0


def test_an_orphan_goes_once_every_kept_dump_is_more_than_a_day_newer(
    db, media_dir, backups
):
    seen = NOW - 10 * DAY
    image_id = orphan_files(media_dir)
    set_first_seen(db, image_id, seen)
    # The oldest dump a day newer to the second: its snapshot may be `seen`.
    dump(backups, "before-restore.dump", seen + DAY)
    nightly(backups, NOW - 3 * DAY, count=3)

    run(db, media_dir, backups)
    assert has_files(media_dir, image_id)
    assert first_seen(db, image_id) == seen

    os.utime(backups / "before-restore.dump", ((seen + DAY).timestamp() + 1,) * 2)
    counts = run(db, media_dir, backups)

    assert not has_files(media_dir, image_id)
    assert first_seen(db, image_id) is None
    assert counts.purged == 1


def test_r2_5_dumps_spanning_60_days_keep_an_orphan_first_seen_45_days_ago(
    db, media_dir, backups
):
    # A backup outage: 30 kept dumps, one every other day, over 60 days.
    nightly(backups, NOW - 60 * DAY, count=30, every=2 * DAY)
    assert len(list(backups.glob("*.dump"))) == 30
    image_id = orphan_files(media_dir)
    set_first_seen(db, image_id, NOW - 45 * DAY)

    run(db, media_dir, backups)

    assert has_files(media_dir, image_id)


def test_a_kept_copy_without_its_date_protects_by_its_name(db, media_dir, backups):
    nightly(backups, NOW - 29 * DAY)
    image_id = orphan_files(media_dir)
    set_first_seen(db, image_id, NOW - 40 * DAY)
    # `cp` without -p: the file is new, the name keeps the dump's day.
    dump(backups, f"kept_{(NOW - 50 * DAY).date().isoformat()}.dump", NOW)

    run(db, media_dir, backups)
    assert has_files(media_dir, image_id)

    (backups / f"kept_{(NOW - 50 * DAY).date().isoformat()}.dump").unlink()
    run(db, media_dir, backups)
    assert not has_files(media_dir, image_id)


@pytest.mark.parametrize(
    "ahead", ["dump file date", "dump name date", "orphan record", "upload"]
)
def test_r5_2_a_clock_behind_a_recorded_date_changes_nothing(
    db, media_dir, backups, caplog, ahead
):
    nightly(backups, NOW - 30 * DAY)
    detached = add_image(db, media_dir, attached_at=NOW - 90 * DAY)
    orphan = orphan_files(media_dir)
    set_first_seen(db, orphan, NOW - 900 * DAY)
    live = add_image(db, media_dir, created_at=NOW - 5 * DAY, on_gift=True)
    later = NOW + timedelta(seconds=1)
    if ahead == "dump file date":
        dump(backups, "before-restore.dump", later)
    elif ahead == "dump name date":
        dump(backups, f"kept_{(NOW + DAY).date().isoformat()}.dump", NOW - DAY)
    elif ahead == "orphan record":
        set_first_seen(db, uuid.uuid4(), later)
    else:
        add_image(db, media_dir, created_at=later)

    with caplog.at_level(logging.INFO, logger="app.media.purge"):
        assert run(db, media_dir, backups) is None

    assert has_row(db, detached) and has_files(media_dir, detached)
    assert first_seen(db, detached) is None
    assert has_files(media_dir, orphan) and first_seen(db, orphan) == NOW - 900 * DAY
    assert modified(media_dir, live) == {NOW - 5 * DAY}
    assert [
        (r.levelno, r.getMessage())
        for r in caplog.records
        if "media purge" in r.getMessage()
    ] == [(logging.WARNING, "media purge: skipped (clock behind)")]


@pytest.mark.parametrize("where", ["unset", "missing", "unreadable", "empty"])
def test_without_a_dump_nothing_is_deleted_and_the_run_is_skipped(
    db, media_dir, backups, tmp_path, caplog, where
):
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("")
    backup_dir = {
        "unset": None,
        "missing": tmp_path / "missing",
        "unreadable": not_a_directory,
        "empty": backups,
    }[where]
    old = add_image(db, media_dir, attached_at=NOW - 90 * DAY)  # detached
    pending = add_image(db, media_dir, created_at=NOW - 90 * DAY)
    orphan = orphan_files(media_dir)
    set_first_seen(db, orphan, NOW - 900 * DAY)
    temporary = media_dir / "gifts" / ".x.webp.abc.tmp"
    temporary.write_bytes(b"")
    os.utime(temporary, ((NOW - 9 * DAY).timestamp(),) * 2)

    with caplog.at_level(logging.INFO, logger="app.media.purge"):
        assert run(db, media_dir, backup_dir) is None

    for image_id in (old, pending, orphan):
        assert has_files(media_dir, image_id)
    assert has_row(db, old) and has_row(db, pending)
    assert first_seen(db, orphan) == NOW - 900 * DAY
    assert temporary.exists()
    lines = [r.getMessage() for r in caplog.records if "media purge" in r.getMessage()]
    assert len(lines) == 1 and lines[0].startswith("media purge: skipped (")


def test_a_row_brought_back_clears_the_record_and_keeps_the_files(
    db, media_dir, backups
):
    image_id = add_image(db, media_dir, attached_at=NOW - 5 * DAY, on_gift=True)
    set_first_seen(db, image_id, NOW - 90 * DAY)
    recent_dumps(backups, NOW - 90 * DAY)

    run(db, media_dir, backups)

    assert first_seen(db, image_id) is None
    assert has_files(media_dir, image_id)


# Rows released (review R1-6) and the orphan clock (review R1-1).


def test_r1_1_a_released_row_restarts_an_old_orphan_clock(db, media_dir, backups):
    # A rollback brought back both A's row (detached) and A's old record.
    a = add_image(db, media_dir, attached_at=NOW - 200 * DAY)
    set_first_seen(db, a, NOW - 100 * DAY)
    nightly(backups, NOW - 20 * DAY, count=21)

    counts = run(db, media_dir, backups)

    assert counts.rows_released == 1 and not has_row(db, a)
    assert first_seen(db, a) == NOW
    assert has_files(media_dir, a)

    run(db, media_dir, backups, now=NOW + 10 * DAY)
    assert has_files(media_dir, a)

    recent_dumps(backups, NOW)
    run(db, media_dir, backups, now=NOW + 5 * DAY)
    assert not has_files(media_dir, a)


def test_r1_1_a_row_gone_during_the_run_resets_its_clock(db, media_dir, backups):
    # The row exists when the run starts and goes between its steps (any path
    # but the purge's own), while an old record for it is there.
    x = add_image(db, media_dir, created_at=NOW - DAY)  # pending, not released
    set_first_seen(db, x, NOW - 100 * DAY)
    # Files dated before the horizon, so only the record keeps them here.
    write_files(media_dir, x, NOW - 100 * DAY)
    nightly(backups, NOW - 20 * DAY, count=21)
    session = Session(db)
    fired = []

    def delete_x():
        fired.append(True)
        with db.begin() as connection:
            connection.execute(text("DELETE FROM images WHERE id = :id"), {"id": x})

    after_step_1(session, delete_x)
    run(db, media_dir, backups, session=session)

    assert fired and not has_row(db, x)
    assert first_seen(db, x) == NOW
    assert has_files(media_dir, x)


def test_r1_1_a_released_row_is_stamped_with_its_deletion(db, media_dir, backups):
    # A run that stops right after releasing A's row (a crash, a restart)
    # leaves A's clock restarted: the stamp is in the deleting transaction.
    a = add_image(db, media_dir, attached_at=NOW - 200 * DAY)
    set_first_seen(db, a, NOW - 100 * DAY)
    nightly(backups, NOW - 20 * DAY, count=21)
    session = Session(db)

    def crash():
        raise RuntimeError("stopped after step 1")

    after_step_1(session, crash)
    with pytest.raises(RuntimeError):
        run(db, media_dir, backups, session=session)

    assert not has_row(db, a)
    assert first_seen(db, a) == NOW


def test_r5_1_files_a_rolled_back_database_forgot_stay_until_the_horizon(
    db, media_dir, backups
):
    def at(day):
        return NOW - 60 * DAY + day * DAY

    def dumps(first, last):
        for path in backups.glob("*.dump"):
            path.unlink()
        nightly(backups, at(first), count=last - first + 1)

    def remove_gift_and(delete_row):
        with db.begin() as connection:
            connection.execute(
                text("DELETE FROM gifts WHERE image_id = :id"), {"id": a}
            )
            if delete_row:
                connection.execute(text("DELETE FROM images WHERE id = :id"), {"id": a})

    # Day 0: A uploaded and attached; day 1, a run sees it live.
    a = add_image(db, media_dir, created_at=at(0), attached_at=at(0), on_gift=True)
    dumps(-28, 1)
    run(db, media_dir, backups, now=at(1))
    # Day 2: A removed from its gift; the run releases its row.
    remove_gift_and(delete_row=False)
    dumps(-27, 2)
    run(db, media_dir, backups, now=at(2))
    assert not has_row(db, a) and first_seen(db, a) == at(2)

    # Day 20: the day-1 dump is restored (A attached, no record), the backup
    # service dumps at once, and a run sees A live.
    with Session(db) as session, session.begin():
        session.execute(delete(MediaOrphan).where(MediaOrphan.name == a.hex))
        session.add(
            Image(id=a, width=10, height=10, created_at=at(0), attached_at=at(0))
        )
        listing = List(title="Birthday", recipient_kind="self")
        session.add(listing)
        session.flush()
        session.add(
            Gift(list_id=listing.id, title="Kite", description="", links=[], image_id=a)
        )
    dumps(-9, 20)
    run(db, media_dir, backups, now=at(20))
    assert first_seen(db, a) is None

    # Day 21: rolled back to before-restore.dump: no row for A, and the day-2
    # record is back.
    remove_gift_and(delete_row=True)
    set_first_seen(db, a, at(2))

    # The horizon has passed day 2, not day 20: the day-20 dump has A.
    dumps(10, 39)
    run(db, media_dir, backups, now=at(40))
    assert has_files(media_dir, a)

    # Once the horizon passes the last run that saw A's row, A goes.
    dumps(22, 51)
    counts = run(db, media_dir, backups, now=at(52))
    assert not has_files(media_dir, a)
    assert counts.purged == 1


def test_a_detached_row_is_released_at_once_and_its_files_wait(db, media_dir, backups):
    detached = add_image(
        db, media_dir, created_at=NOW - timedelta(hours=1), attached_at=NOW
    )
    nightly(backups, NOW - 30 * DAY)

    counts = run(db, media_dir, backups)

    assert counts.rows_released == 1 and not has_row(db, detached)
    assert first_seen(db, detached) == NOW
    assert has_files(media_dir, detached)

    recent_dumps(backups, NOW)
    counts = run(db, media_dir, backups, now=NOW + 5 * DAY)
    assert not has_files(media_dir, detached)
    assert counts.purged == 1


def test_a_never_attached_row_goes_at_48_hours_and_its_files_wait(
    db, media_dir, backups
):
    old = add_image(db, media_dir, created_at=NOW - timedelta(hours=48, seconds=1))
    young = add_image(db, media_dir, created_at=NOW - timedelta(hours=47))
    nightly(backups, NOW - 30 * DAY)

    counts = run(db, media_dir, backups)

    assert counts.rows_released == 1
    assert not has_row(db, old) and first_seen(db, old) == NOW
    assert has_files(media_dir, old)
    assert has_row(db, young) and first_seen(db, young) is None
    assert has_files(media_dir, young)

    recent_dumps(backups, NOW)
    run(db, media_dir, backups, now=NOW + 5 * DAY)
    assert not has_files(media_dir, old)


def test_restore_then_rollback_keeps_the_files_of_a_row_attached_since(
    db, media_dir, backups
):
    # X is pending in the restored dump's state; a newer dump has it attached.
    x = add_image(db, media_dir, created_at=NOW - 3 * DAY)
    nightly(backups, NOW - 30 * DAY)

    run(db, media_dir, backups)
    assert not has_row(db, x) and has_files(media_dir, x)

    # The rollback brings X's row back, attached to its gift.
    with Session(db) as session, session.begin():
        session.add(
            Image(
                id=x,
                width=10,
                height=10,
                created_at=NOW - 3 * DAY,
                attached_at=NOW - 2 * DAY,
            )
        )
        listing = List(title="Birthday", recipient_kind="self")
        session.add(listing)
        session.flush()
        session.add(
            Gift(list_id=listing.id, title="Kite", description="", links=[], image_id=x)
        )
    recent_dumps(backups, NOW)
    run(db, media_dir, backups, now=NOW + 5 * DAY)

    assert first_seen(db, x) is None
    assert has_row(db, x) and has_files(media_dir, x)


# Housekeeping.


def test_old_temporary_files_go_and_unknown_names_stay(db, media_dir, backups):
    nightly(backups, NOW - 30 * DAY)
    gifts = media_dir / "gifts"
    gifts.mkdir(parents=True)
    old_temporary = gifts / f".{uuid.uuid4().hex}.webp.k2j3.tmp"
    new_temporary = gifts / f".{uuid.uuid4().hex}.thumb.webp.x8z1.tmp"
    unknown = [
        gifts / "notes.txt",
        gifts / "export.tmp",  # not one of ours: no leading dot
        gifts / f"{uuid.uuid4().hex.upper()}.webp",
        gifts / f"{uuid.uuid4().hex}.png",
        media_dir / f"{uuid.uuid4().hex}.webp",  # outside gifts/
    ]
    for path in [old_temporary, new_temporary, *unknown]:
        path.write_bytes(b"")
        os.utime(path, ((NOW - 9 * DAY).timestamp(),) * 2)
    os.utime(new_temporary, ((NOW - timedelta(hours=23)).timestamp(),) * 2)
    (gifts / f"{uuid.uuid4().hex}.webp.d").mkdir()

    counts = run(db, media_dir, backups)

    assert not old_temporary.exists()
    assert new_temporary.exists()
    assert all(path.exists() for path in unknown)
    assert counts.orphans == 0
    with Session(db) as session:
        assert session.scalars(select(MediaOrphan)).all() == []


def test_records_of_missing_files_are_dropped(db, media_dir, backups):
    nightly(backups, NOW - 30 * DAY)
    gone = uuid.uuid4()
    set_first_seen(db, gone, NOW - DAY)
    kept = orphan_files(media_dir)
    set_first_seen(db, kept, NOW - DAY)

    run(db, media_dir, backups)

    assert first_seen(db, gone) is None
    assert first_seen(db, kept) == NOW - DAY


def test_the_run_logs_one_line(db, media_dir, backups, caplog):
    nightly(backups, NOW - 30 * DAY)
    orphan_files(media_dir)
    add_image(db, media_dir, attached_at=NOW)

    with caplog.at_level(logging.INFO, logger="app.media.purge"):
        run(db, media_dir, backups)

    lines = [r.getMessage() for r in caplog.records if "media purge" in r.getMessage()]
    assert lines == [
        "media purge: horizon=2026-10-08T00:00:00+00:00 orphans=2 purged=0"
        " rows_released=1"
    ]


# The job (D10).


@pytest.mark.parametrize("with_backups", [False, True])
def test_the_job_runs_with_or_without_a_backup_directory(
    database_url, tmp_path, backups, with_backups
):
    """Without one it only measures sizes (admin panel plan D7, review R1-4);
    `test_the_job_without_a_backup_directory_measures_and_purges_nothing`."""
    settings = {"database_url": database_url, "media_dir": tmp_path / "media"}
    if with_backups:
        settings["backup_dir"] = backups

    with TestClient(create_app(Settings(**settings))) as client:
        job = client.app.state.media_purge
        assert job.is_alive()
        started = time.monotonic()
    assert time.monotonic() - started < 2
    assert not job.is_alive()


def test_the_job_runs_the_purge_with_the_clock(db, media_dir, backups, caplog):
    nightly(backups, NOW - 30 * DAY)
    image_id = orphan_files(media_dir)
    job = MediaPurge(
        sessionmaker(bind=db),
        media_dir,
        backups,
        lambda: NOW,
        first_run_delay=timedelta(0),
    )

    with caplog.at_level(logging.INFO, logger="app.media.purge"):
        job.start()
        deadline = time.monotonic() + 10
        while first_seen(db, image_id) is None and time.monotonic() < deadline:
            time.sleep(0.05)
        job.stop()

    assert first_seen(db, image_id) == NOW
    assert any(
        r.getMessage().startswith("media purge: horizon=") for r in caplog.records
    )


def run_job(db, media_dir, backup_dir, until):
    """Starts the job with no delay, waits for `until()`, then stops it."""
    job = MediaPurge(
        sessionmaker(bind=db),
        media_dir,
        backup_dir,
        lambda: NOW,
        first_run_delay=timedelta(0),
    )
    job.start()
    deadline = time.monotonic() + 10
    while not until() and time.monotonic() < deadline:
        time.sleep(0.05)
    job.stop()


def test_the_job_without_a_backup_directory_measures_and_purges_nothing(
    db, media_dir, caplog
):
    measured = add_image(db, media_dir, attached_at=NOW - 30 * DAY)
    orphan = orphan_files(media_dir)

    with caplog.at_level(logging.INFO, logger="app.media.purge"):
        run_job(db, media_dir, None, lambda: size_of(db, measured) is not None)

    assert size_of(db, measured) == 8
    # The row no gift needs and the orphan are untouched: no purge ran.
    assert has_row(db, measured)
    assert has_files(media_dir, orphan)
    assert first_seen(db, orphan) is None
    assert not any("media purge" in r.getMessage() for r in caplog.records)


def test_the_job_measures_sizes_after_a_skipped_purge(db, media_dir, backups):
    """With a backup directory but no dump to date, the purge is skipped and
    the sizes are measured all the same (review R1-4)."""
    measured = add_image(db, media_dir, on_gift=True)

    run_job(db, media_dir, backups, lambda: size_of(db, measured) is not None)

    assert size_of(db, measured) == 8


# The photo sizes (admin panel plan D7).


def size_of(engine, image_id):
    with Session(engine) as session:
        return session.scalar(select(Image.bytes).where(Image.id == image_id))


def set_size(engine, image_id, size):
    with Session(engine) as session, session.begin():
        session.get_one(Image, image_id).bytes = size


def test_sizes_fill_old_rows_and_skip_missing_files(db, media_dir, monkeypatch, caplog):
    # Batches of 2, so that several batches run.
    monkeypatch.setattr("app.media.purge.SIZES_BATCH", 2)
    old = [add_image(db, media_dir, on_gift=True) for _ in range(5)]
    missing = add_image(db, media_dir, on_gift=True, files=False)
    half = add_image(db, media_dir, on_gift=True)
    image_path(media_dir, half, "thumb").unlink()
    known = add_image(db, media_dir, on_gift=True)
    set_size(db, known, 12345)

    with (
        caplog.at_level(logging.INFO, logger="app.media.purge"),
        Session(db) as session,
    ):
        counts = fill_sizes(session, media_dir)

    assert counts == SizeCounts(filled=5, skipped=2)
    assert [size_of(db, image_id) for image_id in old] == [8] * 5
    assert size_of(db, missing) is None
    assert size_of(db, half) is None
    # Never measured again, whatever the disk says.
    assert size_of(db, known) == 12345
    assert [r.getMessage() for r in caplog.records if r.name == "app.media.purge"] == [
        "media sizes: filled=5 skipped=2"
    ]
    # Nothing on disk was deleted.
    assert all(has_files(media_dir, image_id) for image_id in old)


def test_sizes_with_nothing_to_measure_log_nothing(db, media_dir, caplog):
    known = add_image(db, media_dir, on_gift=True)
    set_size(db, known, 8)

    with (
        caplog.at_level(logging.INFO, logger="app.media.purge"),
        Session(db) as session,
    ):
        assert fill_sizes(session, media_dir) == SizeCounts(0, 0)

    assert [r for r in caplog.records if r.name == "app.media.purge"] == []


def test_sizes_skip_a_row_another_transaction_holds_without_waiting(db, media_dir):
    """An account's deletion sets `uploaded_by` to null on its images: the
    measuring never waits on it, so neither can wait on the other."""
    held = add_image(db, media_dir, on_gift=True)
    free = add_image(db, media_dir, on_gift=True)

    with db.connect() as other, other.begin():
        other.execute(
            text("SELECT 1 FROM images WHERE id = :id FOR UPDATE"), {"id": held}
        )
        started = time.monotonic()
        with Session(db) as session:
            counts = fill_sizes(session, media_dir)
        assert time.monotonic() - started < 2

    assert counts == SizeCounts(filled=1, skipped=0)
    assert size_of(db, held) is None
    assert size_of(db, free) == 8
