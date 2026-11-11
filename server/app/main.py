"""The FastAPI application: `uvicorn app.main:app`, run from server/."""

import contextlib
import logging
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

from app import app_links
from app.accounts import apple_tokens, sessions
from app.accounts.apple import AppleVerifier
from app.accounts.apple_router import router as apple_router
from app.accounts.email_router import router as email_router
from app.accounts.google import GoogleVerifier
from app.accounts.router import router as accounts_router
from app.admin.router import router as admin_router
from app.billing import apple_gateway, google_gateway
from app.billing.router import router as billing_router
from app.billing.stripe_gateway import StripeGateway
from app.comments.router import router as comments_router
from app.db import create_db_engine, create_session_factory
from app.hidden_gifts.router import router as hidden_gifts_router
from app.lists.router import router as lists_router
from app.media.purge import MediaPurge
from app.media.router import router as media_router
from app.notifications.digests import EmailConfig
from app.notifications.mailer import BrevoMailer
from app.notifications.router import router as notifications_router
from app.notifications.worker import NotificationWorker
from app.reserving.router import router as reserving_router
from app.safe_fetch import SafeFetcher
from app.settings import Settings

_log = logging.getLogger(__name__)

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
        # Everywhere, for the photo sizes (admin panel plan D7); it purges
        # only where dumps can be dated (gift images plan D10). Stopped before
        # the engine goes.
        app.state.media_purge = MediaPurge(
            app.state.session_factory,
            settings.media_dir,
            settings.backup_dir,
            lambda: app.state.clock(),
        )
        app.state.media_purge.start()
        # Stopped before the engine goes too (comments plan D16).
        app.state.notification_worker = None
        if settings.notifications_worker:
            app.state.notification_worker = NotificationWorker(
                app.state.session_factory,
                lambda: app.state.mailer,
                EmailConfig.from_settings(settings),
                lambda: app.state.clock(),
            )
            app.state.notification_worker.start()
        yield
        if app.state.notification_worker is not None:
            app.state.notification_worker.stop()
        app.state.media_purge.stop()
        engine.dispose()

    # Outside DEV, no schema or docs page lists the admin routes (admin panel
    # plan D2, reviews R1-2, R2-1: VAL is public too); `app.openapi()` still
    # builds the schema.
    hidden = settings.app_env != "dev"
    app = FastAPI(
        title="Shush Gift",
        version=settings.app_version,
        lifespan=lifespan,
        openapi_url=None if hidden else "/openapi.json",
        docs_url=None if hidden else "/docs",
        redoc_url=None if hidden else "/redoc",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    # Replaced by tests: no test calls Google, waits for the clock or fetches
    # from the network.
    app.state.google_verifier = (
        GoogleVerifier(settings.google_audiences) if settings.google_audiences else None
    )
    app.state.apple_verifier = (
        AppleVerifier(settings.apple_audiences) if settings.apple_audiences else None
    )
    # None while revocation is off: no code is exchanged and no token kept
    # (iOS app plan D5). Replaced by tests: none calls Apple.
    signer, revocation_gaps = apple_tokens.signer_from(settings)
    app.state.apple_tokens = (
        apple_tokens.AppleTokens(signer)
        if signer is not None and settings.apple_audiences
        else None
    )
    app.state.clock = sessions.utc_now
    app.state.url_fetcher = SafeFetcher(version=settings.app_version)
    # None until every variable it needs is set: the worker then skips the
    # digests that come due (comments plan D19).
    app.state.mailer = (
        None
        if settings.missing_email_settings
        else BrevoMailer(
            settings.brevo_api_key,
            settings.email_sender_address,
            settings.email_sender_name,
        )
    )
    # None until its secrets are set; replaced by tests (premium plan D10).
    app.state.stripe_gateway = (
        StripeGateway(
            settings.stripe_secret_key.strip(), settings.stripe_webhook_secret.strip()
        )
        if settings.billing_gateway_configured
        else None
    )
    # None until every variable it needs is set and its key loads (Apple IAP
    # plan D7); replaced by tests, which never reach Apple.
    app.state.apple_gateway, apple_gaps = apple_gateway.from_settings(settings)
    # The same for Google Play (Android release plan D6); replaced by tests,
    # which never reach Google.
    app.state.google_gateway, google_gaps = google_gateway.from_settings(settings)
    _log_billing_gaps(settings)
    _log_apple_purchase_gaps(settings, apple_gaps)
    _log_google_purchase_gaps(settings, google_gaps)
    _log_email_sign_in_gap(settings)
    _log_admin_gap(settings)
    _log_apple_revocation_gap(settings, revocation_gaps)
    _log_app_links_gap(settings)

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
    def config() -> dict[str, str | bool | None]:
        # Read by the clients at start, so one build serves every environment
        # (accounts plan D6). The first client ID is the web client's.
        audiences = settings.google_audiences
        apple_audiences = settings.apple_audiences
        # Without its trailing slash: the client appends /join#<token>.
        public_base_url = settings.public_base_url.strip().rstrip("/")
        return {
            "google_client_id": audiences[0] if audiences else None,
            "public_base_url": public_base_url or None,
            # What the sign-in screen offers (sign-in plan D18).
            "apple_client_id": apple_audiences[0] if apple_audiences else None,
            "apple_redirect_uri": settings.apple_redirect_uri,
            "email_sign_in": (
                app.state.mailer is not None
                and bool(settings.notification_secret.strip())
            ),
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
    app.include_router(email_router)
    app.include_router(apple_router)
    app.include_router(lists_router)
    app.include_router(media_router)
    app.include_router(reserving_router)
    app.include_router(hidden_gifts_router)
    app.include_router(comments_router)
    app.include_router(notifications_router)
    app.include_router(billing_router)
    app.include_router(admin_router)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app_links.register(app, settings)

    # Registered last, so every route above takes precedence.
    if web_dir.is_dir():
        _serve_web_client(app, web_dir)

    return app


def _log_billing_gaps(settings: Settings) -> None:
    """Names what keeps the app from selling, once, when billing is asked for
    (premium plan D16). With nothing asked for, none of this is a gap."""
    asked = settings.billing_enforce_limits or any(
        value.strip()
        for value in (
            settings.stripe_secret_key,
            settings.stripe_webhook_secret,
            settings.stripe_price_id,
        )
    )
    if asked and settings.missing_selling_settings:
        _log.warning(
            "billing is not selling; missing or invalid: %s",
            ", ".join(settings.missing_selling_settings),
        )


def _log_apple_purchase_gaps(settings: Settings, gaps: list[str]) -> None:
    """Names what keeps the app from selling on iPhone, once, when it is asked
    for (Apple IAP plan D7). Never a value: the key is a secret."""
    asked = any(
        value.strip()
        for value in (
            settings.apple_product_id,
            settings.apple_iap_issuer_id,
            settings.apple_iap_key_id,
            settings.apple_iap_private_key,
        )
    )
    if asked and gaps:
        _log.warning(
            "selling on iPhone is off; missing or invalid: %s", ", ".join(gaps)
        )


def _log_google_purchase_gaps(settings: Settings, gaps: list[str]) -> None:
    """Names what keeps the app from selling on Android, once, when it is
    asked for (Android release plan D6). Never a value: the key is a
    secret."""
    asked = any(
        value.strip()
        for value in (
            settings.google_play_product_id,
            settings.google_play_package_name,
            settings.google_play_service_account_json,
            settings.google_play_pubsub_audience,
            settings.google_play_pubsub_service_account,
        )
    )
    if asked and gaps:
        _log.warning(
            "selling on Android is off; missing or invalid: %s", ", ".join(gaps)
        )


def _log_admin_gap(settings: Settings) -> None:
    """An entry of ADMIN_USER_IDS that is not an id makes no one admin (admin
    panel plan D1, review R2-3). Named by its position only: the value may be
    an address, and no address is logged."""
    if settings.admin_ids_invalid:
        _log.warning(
            "ADMIN_USER_IDS: entries at positions %s are not account ids; ignored",
            ", ".join(str(position) for position in settings.admin_ids_invalid),
        )


def _log_apple_revocation_gap(settings: Settings, gaps: list[str]) -> None:
    """Apple requires an app offering its sign-in to revoke the person's token
    at account deletion (iOS app plan D5): with Apple sign-in on, what keeps
    that off is named, once. Never a value: the key is a secret."""
    if settings.apple_audiences and gaps:
        _log.warning(
            "Apple token revocation is off; missing or unloadable: %s",
            ", ".join(gaps),
        )


def _log_app_links_gap(settings: Settings) -> None:
    """An app-link entry that is not valid is left out of its file (Shush Gift
    plan D7): named once, by its position, as ADMIN_USER_IDS."""
    if settings.app_links_invalid:
        _log.warning(
            "app links: invalid entries ignored: %s",
            "; ".join(settings.app_links_invalid),
        )


def _log_email_sign_in_gap(settings: Settings) -> None:
    """The worker sends the links: without it they would expire unsent
    (sign-in plan D18, review R1-5)."""
    if not settings.missing_email_settings and not settings.notifications_worker:
        _log.warning(
            "email sign-in is configured but NOTIFICATIONS_WORKER is off:"
            " its links will not be sent"
        )


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
