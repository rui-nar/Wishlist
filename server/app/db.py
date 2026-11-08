"""Database engine, sessions and the declarative base for models."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base of every model; Alembic compares its metadata with the database."""


def create_db_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        # A connection dropped by a Postgres restart is replaced, not handed out.
        pool_pre_ping=True,
        # Fail fast when the server does not answer, so /api/health reports it
        # instead of hanging.
        connect_args={"connect_timeout": 5},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)
