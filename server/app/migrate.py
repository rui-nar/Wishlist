"""Migrate the database on start: `python -m app.migrate`, run from server/.

What the image's entrypoint runs instead of `alembic upgrade head` (plan
ACCOUNTS D13). A database at a revision this image's scripts do not know is
ahead of the image: a rollback, or VAL seeded from a newer PROD. Upgrading
would fail with "Can't locate revision" and the app would restart in a loop,
so it starts without migrating instead. That is safe because every migration
keeps the previous release working (DevOps plan D15).
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.db import create_db_engine
from app.settings import Settings

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

logger = logging.getLogger("app.migrate")


def unknown_database_heads(config: Config, database_url: str) -> list[str]:
    """The database's revisions that this image's scripts do not know."""
    script = ScriptDirectory.from_config(config)
    known = {revision.revision for revision in script.walk_revisions()}
    engine = create_db_engine(database_url)
    try:
        with engine.connect() as connection:
            heads = MigrationContext.configure(connection).get_current_heads()
    finally:
        engine.dispose()
    return [head for head in heads if head not in known]


def main() -> None:
    # WARNING keeps the revision check quiet; env.py replaces this with
    # alembic.ini's logging once an upgrade runs.
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s"
    )
    config = Config(str(ALEMBIC_INI))
    unknown = unknown_database_heads(config, Settings().database_url)
    if unknown:
        image_heads = ScriptDirectory.from_config(config).get_heads()
        logger.warning(
            "database at revision %s, unknown to this image (head %s): "
            "starting without migrating; see docs/DEPLOYMENT.md Rollback",
            ", ".join(unknown),
            ", ".join(image_heads),
        )
        return
    command.upgrade(config, "head")


if __name__ == "__main__":
    # Any other failure raises: a traceback and a non-zero exit stop the start.
    main()
