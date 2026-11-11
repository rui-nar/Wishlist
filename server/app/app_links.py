"""The app-link files (Shush Gift plan D7), from which iOS and Android check
that this host lets the installed app open its links.

Both are configuration only, the same for whoever asks, and built once from
settings. Apple and Google fetch them without following redirects and want
`application/json`, so each is answered directly here, ahead of the web
catch-all; with its settings empty, a file answers 404.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from app.settings import Settings

# The paths that open the app (D7). Each matches its path exactly, or below it
# where it ends in `*`, so `/account` claims neither `/account/plan` (Stripe's
# return, sold on the web only) nor anything else left to the browser:
# `/unsubscribe`, `/legal/*`, `/api/*`, `/welcome`. A component without a `?`
# or `#` key matches any query and any fragment, as `/join#<token>`,
# `/create-account#<token>` and `/shared/<occasion>?gift=<gift>` carry.
APP_PATHS = ("/join", "/shared/*", "/create-account", "/reset-password", "/account")


def apple_app_site_association(app_ids: list[str]) -> dict[str, Any]:
    return {
        "applinks": {
            "details": [
                {
                    "appIDs": app_ids,
                    "components": [{"/": path} for path in APP_PATHS],
                }
            ]
        }
    }


def asset_links(package: str, fingerprints: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": package,
                "sha256_cert_fingerprints": fingerprints,
            },
        }
    ]


def register(app: FastAPI, settings: Settings) -> None:
    """Adds the two routes. Registered before the web catch-all, which would
    otherwise answer them with index.html."""
    apple_ids = settings.app_links_apple_ids
    package = settings.app_links_android_app
    fingerprints = settings.app_links_android_fingerprints
    aasa = apple_app_site_association(apple_ids) if apple_ids else None
    assetlinks = (
        asset_links(package, fingerprints) if package and fingerprints else None
    )

    @app.api_route(
        "/.well-known/apple-app-site-association",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    def apple_file() -> Response:
        return _answer(aasa)

    @app.api_route(
        "/.well-known/assetlinks.json", methods=["GET", "HEAD"], include_in_schema=False
    )
    def android_file() -> Response:
        return _answer(assetlinks)


def _answer(content: Any) -> Response:
    if content is None:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return JSONResponse(content)
