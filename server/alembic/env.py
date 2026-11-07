from logging.config import fileConfig

from alembic import context

from app.db import Base, create_db_engine
from app.settings import Settings

config = context.config

# disable_existing_loggers=False: the default would silence loggers created
# before this point if migrations are ever run from inside the app process.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Models must be imported before this line once they exist, so that their
# tables are registered on Base.metadata for autogenerate and `alembic check`.
target_metadata = Base.metadata

# Always the URL the app uses (DATABASE_URL), never a value from alembic.ini.
database_url = Settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_db_engine(database_url)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
