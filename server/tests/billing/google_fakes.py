"""Google Play, in tests (Android release plan Conventions).

Pub/Sub's tokens are signed by a key made here, whose certificate is served
as the transport the verifier fetches Google's certificates with, so the
verification runs for real. The Play Developer API answers from a dict. No
test reaches Google.
"""

import base64
import copy
import json
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from google.auth import crypt, jwt

from app.accounts import sessions
from app.billing import google_events
from app.billing.google_gateway import MissingAtGoogle, PushVerifier

PACKAGE = "com.example.shushgift"
PRODUCT_ID = "premium_yearly"
AUDIENCE = "https://shushgift.example.test/api/billing/google/notifications"
PUSH_ACCOUNT = "play-push@example-project.iam.gserviceaccount.com"
TOKEN = "token-1.AO-J1Oa"
ORDER = "GPA.3301-1234-5678-90123"


def rfc3339(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _key_and_certificate() -> tuple[rsa.RSAPrivateKey, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, certificate.public_bytes(serialization.Encoding.PEM).decode()


def private_pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class GoogleKeys:
    """Google's side of Pub/Sub's push authentication, without Google: signs
    tokens with a key of its own and serves its certificate as the transport
    the verifier fetches Google's certificates with. `fetches` counts them;
    `unavailable` makes the fetch fail."""

    KEY_ID = "test-key"

    def __init__(self) -> None:
        key, certificate = _key_and_certificate()
        self.certificates = {self.KEY_ID: certificate}
        self.signer = crypt.RSASigner.from_string(private_pem(key), key_id=self.KEY_ID)
        self.fetches = 0
        self.unavailable = False

    def __call__(self, url: str, method: str = "GET", **kwargs: Any) -> Any:
        self.fetches += 1
        if self.unavailable:
            return SimpleNamespace(status=503, data=b"")
        return SimpleNamespace(status=200, data=json.dumps(self.certificates).encode())

    def token(self, signer: Any = None, **claims: Any) -> str:
        """A Pub/Sub push token, valid now unless overridden."""
        now = int(time.time())
        payload = {
            "iss": "https://accounts.google.com",
            "aud": AUDIENCE,
            "sub": "112233445566778899",
            "email": PUSH_ACCOUNT,
            "email_verified": True,
            "iat": now,
            "exp": now + 3600,
        } | claims
        return jwt.encode(signer or self.signer, payload).decode()

    def headers(self, **claims: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(**claims)}"}

    def verifier(self) -> PushVerifier:
        return PushVerifier(AUDIENCE, PUSH_ACCOUNT, request=self)


def other_signer() -> Any:
    """A key Google never published, under the same key id."""
    key, _ = _key_and_certificate()
    return crypt.RSASigner.from_string(private_pem(key), key_id=GoogleKeys.KEY_ID)


def purchase(
    user_id: uuid.UUID | str | None,
    state: str = google_events.STATE_ACTIVE,
    expires: datetime | None = None,
    product: str = PRODUCT_ID,
    auto_renew: bool = True,
    test: bool = True,
    acknowledged: bool = False,
    linked: str | None = None,
    expired_token: str | None = None,
    started: datetime | None = None,
    order: str = ORDER,
) -> dict[str, Any]:
    """A `SubscriptionPurchaseV2` as the Play Developer API answers it,
    bearing `user_id` as its account id (none when None). A test purchase
    unless `test` is false: that is what DEV and VAL accept."""
    now = sessions.utc_now()
    answer: dict[str, Any] = {
        "kind": "androidpublisher#subscriptionPurchaseV2",
        "regionCode": "FR",
        "startTime": rfc3339(started or now),
        "subscriptionState": state,
        "latestOrderId": order,
        "acknowledgementState": (
            "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
            if acknowledged
            else google_events.ACKNOWLEDGEMENT_PENDING
        ),
        "lineItems": [
            {
                "productId": product,
                "expiryTime": rfc3339(expires or now + timedelta(days=365)),
                "autoRenewingPlan": {"autoRenewEnabled": auto_renew},
                "offerDetails": {"basePlanId": "yearly"},
                "latestSuccessfulOrderId": order,
            }
        ],
    }
    if user_id is not None:
        answer["externalAccountIdentifiers"] = {
            "obfuscatedExternalAccountId": str(user_id)
        }
    if test:
        answer["testPurchase"] = {}
    if linked is not None:
        answer["linkedPurchaseToken"] = linked
    if expired_token is not None:
        answer["outOfAppPurchaseContext"] = {"expiredPurchaseToken": expired_token}
    return answer


def developer_notification(
    token: str = TOKEN, kind: str = "subscription", package: str = PACKAGE
) -> dict[str, Any]:
    """A `DeveloperNotification` pointing at `token`: `subscription` (a
    renewal), `voided` (a refund) or `test`."""
    notification: dict[str, Any] = {
        "version": "1.0",
        "packageName": package,
        "eventTimeMillis": str(int(time.time() * 1000)),
    }
    if kind == "subscription":
        notification["subscriptionNotification"] = {
            "version": "1.0",
            "notificationType": 2,
            "purchaseToken": token,
            "subscriptionId": PRODUCT_ID,
        }
    elif kind == "voided":
        notification["voidedPurchaseNotification"] = {
            "purchaseToken": token,
            "orderId": ORDER,
            "productType": 1,
            "refundType": 1,
        }
    else:
        notification["testNotification"] = {"version": "1.0"}
    return notification


def push_body(notification: dict[str, Any]) -> dict[str, Any]:
    """Pub/Sub's push around a notification."""
    data = base64.b64encode(json.dumps(notification).encode()).decode()
    return {
        "message": {"data": data, "messageId": "1", "publishTime": "2026"},
        "subscription": "projects/example/subscriptions/play",
    }


class FakeGoogle:
    """Stands in for `app.state.google_gateway`, a GoogleGateway: the push's
    verification runs for real, against `keys`; the Play Developer API
    answers from `purchases`. Records every API call in `calls`; a name in
    `failures` raises that exception; `on_call` runs inside each call, for
    the concurrency tests."""

    def __init__(self, keys: GoogleKeys) -> None:
        self.keys = keys
        self.push = keys.verifier()
        self.product_id = PRODUCT_ID
        self.purchases: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, Any]] = []
        self.failures: dict[str, Exception] = {}
        self.on_call: Callable[[str], None] | None = None
        self._lock = threading.Lock()

    def _called(self, name: str, *args: Any) -> None:
        with self._lock:
            self.calls.append((name, args))
        if self.on_call is not None:
            self.on_call(name)
        if name in self.failures:
            raise self.failures[name]

    def called(self, name: str) -> list[Any]:
        return [args for called, args in self.calls if called == name]

    def verify_push(self, authorization: str | None) -> None:
        self.push.verify(authorization)

    def subscription(self, token: str) -> dict[str, Any]:
        # Read before `on_call`: a read that stalls has the state of its start.
        answer = copy.deepcopy(self.purchases.get(token))
        self._called("subscription", token)
        if answer is None:
            raise MissingAtGoogle()
        return answer

    def acknowledge(self, token: str) -> None:
        self._called("acknowledge", token)
        if token not in self.purchases:
            raise MissingAtGoogle()
        self.purchases[token]["acknowledgementState"] = (
            "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
        )

    def cancel(self, token: str) -> None:
        self._called("cancel", token)
        if token not in self.purchases:
            raise MissingAtGoogle()
        found = self.purchases[token]
        found["subscriptionState"] = google_events.CANCELED
        for item in found["lineItems"]:
            item["autoRenewingPlan"]["autoRenewEnabled"] = False

    def add(self, token: str, user_id: Any, **fields: Any) -> dict[str, Any]:
        """The purchase as the Play Developer API will answer it."""
        self.purchases[token] = purchase(user_id, **fields)
        return self.purchases[token]
