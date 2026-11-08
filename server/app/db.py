"""Database engine, sessions and the declarative base for models."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base of every model; Alembic compares its metadata with the database."""

    # Named constraints, so a later migration can alter or drop one by a name
    # known in advance rather than one Postgres made up.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


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


def db_session(request: Request) -> Iterator[Session]:
    """One unit of work per request (accounts plan D9).

    Committed when the request succeeds, rolled back when it raises, so a
    write made by a dependency (the session touch in `current_user`) is kept
    on a request whose endpoint writes nothing itself.
    """
    with request.app.state.session_factory.begin() as session:
        yield session


# scope="function": the commit runs before the response is sent, so a client
# never gets a 200 for a write that then fails to commit, nor a token whose
# session is not yet visible to its next request. Every user of the session
# goes through this alias, so a request shares one session and one transaction.
DbSession = Annotated[Session, Depends(db_session, scope="function")]
