"""The FastAPI application: `uvicorn app.main:app`, run from server/."""

import contextlib
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.convertors import PathConvertor, register_url_convertor
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.accounts import sessions
from app.accounts.google import GoogleVerifier
from app.accounts.router import router as accounts_router
from app.db import create_db_engine, create_session_factory
from app.lists.router import router as lists_router
from app.media.router import router as media_router
from app.settings import Settings

# The Flutter web build. The image puts it in /app/web, next to /app/server;
# locally the directory does not exist and the app serves the API only.
WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class _WebPathConvertor(PathConvertor):
    """A path that is never /api or /api/... .

    An unknown /api/... path is a missing endpoint, never a client route: it
    must get the API's JSON 404, not index.html with a 200 that an out-of-date
    client could take for a real response. Keeping /api out of the catch-all's
    pattern, rather than raising inside it, also keeps the catch-all from
    matching API paths at all (a POST would get its 405), so the API answers
    the same whether or not a web build is present.
    """

    regex = r"(?!api(?:/|$)).*"


register_url_convertor("web_path", _WebPathConvertor())


def create_app(settings: Settings | None = None, web_dir: Path = WEB_DIR) -> FastAPI:
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
    # Both replaced by tests: no test calls Google or waits for the clock.
    app.state.google_verifier = (
        GoogleVerifier(settings.google_audiences) if settings.google_audiences else None
    )
    app.state.clock = sessions.utc_now

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

    @app.get("/api/config")
    def config() -> dict[str, str | None]:
        # Read by the clients at start, so one build serves every environment
        # (accounts plan D6). The first client ID is the web client's.
        audiences = settings.google_audiences
        # Without its trailing slash: the client appends /join#<token>.
        public_base_url = settings.public_base_url.strip().rstrip("/")
        return {
            "google_client_id": audiences[0] if audiences else None,
            "public_base_url": public_base_url or None,
        }

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

    app.include_router(accounts_router)
    app.include_router(lists_router)
    app.include_router(media_router)
    app.add_exception_handler(RequestValidationError, _validation_error)

    # Registered last, so every /api route above takes precedence.
    if web_dir.is_dir():
        _serve_web_client(app, web_dir)

    return app


def _serve_web_client(app: FastAPI, web_dir: Path) -> None:
    # StaticFiles does the lookup: it refuses paths that resolve outside
    # web_dir and answers a matching If-None-Match with a 304.
    static = StaticFiles(directory=web_dir)

    @app.api_route("/{path:web_path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def web_client(path: str, request: Request) -> Response:
        try:
            response = await static.get_response(path, request.scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            # Not a file of the build: a client-side route, which the client's
            # router resolves once index.html has loaded it.
            response = await static.get_response("index.html", request.scope)
        # Flutter puts no content hash in its file names (index.html,
        # flutter_bootstrap.js, main.dart.js...), so a cached copy would keep a
        # returning user on the previous release after a deploy, out of step
        # with the API (plan D5). The browser revalidates on every load
        # instead; the ETag makes an unchanged file a cheap 304.
        response.headers["Cache-Control"] = "no-cache"
        return response


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    # FastAPI's default 422 body quotes each invalid value back, and a value
    # may be a token (an oversized ID token, a password later): only where and
    # why a value was refused goes out.
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"type": error["type"], "loc": error["loc"], "msg": error["msg"]}
                for error in exc.errors()
            ]
        },
    )


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
