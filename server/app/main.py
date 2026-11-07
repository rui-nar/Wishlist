"""The FastAPI application: `uvicorn app.main:app`, run from server/."""

import contextlib
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.db import create_db_engine, create_session_factory
from app.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = create_db_engine(settings.database_url)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Locally the directory may not exist yet; on the VPS it is a mount and
        # this is a no-op. A failure does not stop the API: /api/health reports
        # the directory as not writable.
        with contextlib.suppress(OSError):
            settings.media_dir.mkdir(parents=True, exist_ok=True)
        yield
        engine.dispose()

    app = FastAPI(title="Wishlist", version=settings.app_version, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)

    # The DEV client is served by `flutter run` on its own port, so it is
    # cross-origin; in VAL and PROD the web client comes from the same origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/version")
    def version() -> dict[str, str]:
        return {"version": settings.app_version, "env": settings.app_env}

    @app.get("/api/health")
    def health() -> JSONResponse:
        # Only fixed words in the body: the endpoint is public, and error texts
        # carry host names, user names and paths.
        database = "ok" if _database_ok(engine) else "unreachable"
        media = "ok" if _media_writable(settings.media_dir) else "not writable"
        healthy = database == "ok" and media == "ok"
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ok" if healthy else "error",
                "database": database,
                "media": media,
            },
        )

    return app


def _database_ok(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


def _media_writable(media_dir: Path) -> bool:
    try:
        fd, path = tempfile.mkstemp(dir=media_dir, prefix=".health-")
        try:
            os.write(fd, b"ok")
        finally:
            os.close(fd)
            os.unlink(path)
    except OSError:
        return False
    return True


app = create_app()
