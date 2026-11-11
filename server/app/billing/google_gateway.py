"""Google Play, behind one module (Android release plan D6).

The only module that imports Google's client libraries for billing: plain
HTTPS to the Play Developer API through `google-auth`'s authorised session,
with a service account, and google-auth again to verify Pub/Sub's pushes.
Google's answers can be late, wrong, missing or hostile, so everything leaves
here as a plain dict or a typed exception: no key, token, purchase token or
Google message goes into a log line or an exception, only fixed words and
numbers.
"""

import json
import logging
from typing import Any
from urllib.parse import quote

import jwt
from google.auth import exceptions as google_exceptions
from google.auth import transport
from google.auth.transport import requests as google_requests
from google.oauth2 import service_account
from google.oauth2.id_token import verify_oauth2_token

from app.billing import google_events
from app.settings import Settings

_log = logging.getLogger(__name__)

_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
_API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
# Per call, in seconds: connecting, then reading Google's answer.
_TIMEOUT = (5, 30)
# Google mints Pub/Sub's tokens against its own clock (accounts/google.py).
_CLOCK_SKEW_SECONDS = 10
# The answers that mean Google does not know the purchase, or no longer does.
_NOT_FOUND = frozenset({400, 404, 410})

# One transport for the process, which fetches Google's certificates for the
# pushes' tokens.
_google_request = google_requests.Request()


class GoogleError(Exception):
    """Google's answer, reduced to its meaning: its text stays out."""


class GoogleUnavailable(GoogleError):
    """Google failed, refused or answered something unusable; retrying later
    is safe."""


class MissingAtGoogle(GoogleError):
    """Google does not know this purchase."""


class InvalidPush(Exception):
    """Not a push from the configured Pub/Sub subscription. Why it failed is
    nobody's business."""


class PushVerifier:
    """Verifies the OIDC token Pub/Sub sends with each push: Google's
    signature and issuer, the audience, and the configured service account's
    verified email (D6)."""

    def __init__(
        self,
        audience: str,
        service_account_email: str,
        request: transport.Request = _google_request,
    ) -> None:
        self._audience = audience
        self._email = service_account_email
        self._request = request

    def verify(self, authorization: str | None) -> None:
        scheme, _, token = (authorization or "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise InvalidPush()
        # Before Google's certificates are fetched: anything not even shaped
        # like a signed token costs no request.
        try:
            header = jwt.get_unverified_header(token)
        except Exception:
            raise InvalidPush() from None
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise InvalidPush()
        try:
            claims = verify_oauth2_token(
                token,
                self._request,
                self._audience,
                clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
            )
        except google_exceptions.TransportError:
            _log.warning("google: Google's certificates could not be fetched")
            raise GoogleUnavailable() from None
        except Exception:
            raise InvalidPush() from None
        verified = claims.get("email_verified")
        if claims.get("email") != self._email or not (
            verified is True or verified == "true"
        ):
            raise InvalidPush()


class GoogleGateway:
    """Constructed once, only when selling on Android is configured (D6)."""

    def __init__(
        self,
        push: PushVerifier,
        package_name: str,
        product_id: str,
        session: Any,
    ) -> None:
        self._push = push
        self.product_id = product_id
        self._session = session
        self._base = f"{_API}/{quote(package_name, safe='')}/purchases"

    def verify_push(self, authorization: str | None) -> None:
        self._push.verify(authorization)

    def subscription(self, token: str) -> dict[str, Any]:
        """The purchase as Google has it now (`purchases.subscriptionsv2`)."""
        answer = self._call(
            "GET", f"{self._base}/subscriptionsv2/tokens/{_path(token)}", "read"
        )
        if not isinstance(answer, dict):
            _log.warning("google: read: an answer that is no purchase")
            raise GoogleUnavailable()
        return answer

    def acknowledge(self, token: str) -> None:
        """Keeps Google from refunding the purchase on the third day."""
        self._call("POST", self._v1(token, "acknowledge"), "acknowledge", body={})

    def cancel(self, token: str) -> None:
        """Stops the renewals; what was paid runs to its end (D6, deletion)."""
        self._call("POST", self._v1(token, "cancel"), "cancel")

    def _v1(self, token: str, action: str) -> str:
        product = quote(self.product_id, safe="")
        return f"{self._base}/subscriptions/{product}/tokens/{_path(token)}:{action}"

    def _call(
        self, method: str, url: str, name: str, body: dict[str, Any] | None = None
    ) -> Any:
        try:
            response = self._session.request(method, url, json=body, timeout=_TIMEOUT)
        except google_exceptions.RefreshError:
            # Not a blip: nothing works until the key is fixed.
            _log.error("google: %s: the service account's key was refused", name)
            raise GoogleUnavailable() from None
        except Exception as exc:
            # The exception's text can quote the URL, and so the token.
            _log.warning("google: %s: %s", name, type(exc).__name__)
            raise GoogleUnavailable() from None
        status = response.status_code
        if status in _NOT_FOUND:
            _log.warning("google: %s: not found (HTTP %s)", name, status)
            raise MissingAtGoogle()
        if status in (401, 403):
            _log.error(
                "google: %s: refused (HTTP %s): check the service account's"
                " permissions in the Play Console",
                name,
                status,
            )
            raise GoogleUnavailable()
        if not 200 <= status < 300:
            _log.warning("google: %s: HTTP %s", name, status)
            raise GoogleUnavailable()
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            _log.warning("google: %s: an answer that is no JSON", name)
            raise GoogleUnavailable() from None


def _path(token: str) -> str:
    """A token into a URL path: only one made of what Google uses."""
    if not google_events.is_token(token):
        raise MissingAtGoogle()
    return token


def from_settings(settings: Settings) -> tuple[GoogleGateway | None, list[str]]:
    """The gateway, or None and the variables that keep selling on Android
    off, missing or unloadable, by the name the operator sets. Never a value:
    the key is a secret."""
    gaps = list(settings.missing_google_settings)
    text = settings.google_play_service_account_json
    credentials = _credentials(text) if text.strip() else None
    if text.strip() and credentials is None:
        gaps.append("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON")
    if gaps or credentials is None:
        return None, gaps
    push = PushVerifier(
        settings.google_play_pubsub_audience.strip(),
        settings.google_play_pubsub_service_account.strip(),
    )
    gateway = GoogleGateway(
        push,
        settings.google_play_package_name.strip(),
        settings.google_play_product_id.strip(),
        google_requests.AuthorizedSession(credentials),
    )
    return gateway, []


def _credentials(text: str) -> service_account.Credentials | None:
    """The service account's credentials from its JSON key, or None: why it
    failed would quote the key."""
    try:
        info = json.loads(text)
        if not isinstance(info, dict):
            return None
        return service_account.Credentials.from_service_account_info(
            info, scopes=[_SCOPE]
        )
    except Exception:
        return None
