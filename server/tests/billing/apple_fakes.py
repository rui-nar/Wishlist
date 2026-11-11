"""Apple, in tests (Apple IAP plan Conventions).

A certificate chain shaped like Apple's, built here, signs every payload, and
the gateway's verification runs for real against its root. Nothing is
downloaded and no test reaches Apple.
"""

import base64
import copy
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.accounts import sessions
from app.billing.apple_events import AppleSubscription
from app.billing.apple_gateway import MissingAtApple, SignedData

BUNDLE_ID = "com.example.wishlist"
PRODUCT_ID = "example.premium.yearly"
APP_APPLE_ID = 1234567890
# The extensions Apple's library requires on its leaf and intermediate.
LEAF_OID = "1.2.840.113635.100.6.11.1"
INTERMEDIATE_OID = "1.2.840.113635.100.6.2.1"


@dataclass(frozen=True)
class ApplePki:
    """A root, an intermediate and a leaf, like Apple's. `x5c` is the chain a
    payload's header carries."""

    root_der: bytes
    leaf_key: ec.EllipticCurvePrivateKey
    x5c: list[str]


def build_apple_pki(leaf_oid: str = LEAF_OID) -> ApplePki:
    root_key, intermediate_key, leaf_key = (
        ec.generate_private_key(ec.SECP256R1()) for _ in range(3)
    )
    root = _certificate(root_key, "Test Root", root_key, "Test Root", None)
    intermediate = _certificate(
        intermediate_key, "Test Intermediate", root_key, "Test Root", INTERMEDIATE_OID
    )
    leaf = _certificate(
        leaf_key, "Test Leaf", intermediate_key, "Test Intermediate", leaf_oid
    )
    der = [
        cert.public_bytes(serialization.Encoding.DER)
        for cert in (leaf, intermediate, root)
    ]
    return ApplePki(
        root_der=der[2],
        leaf_key=leaf_key,
        x5c=[base64.b64encode(value).decode() for value in der],
    )


def _certificate(
    key: ec.EllipticCurvePrivateKey,
    subject: str,
    issuer_key: ec.EllipticCurvePrivateKey,
    issuer: str,
    apple_oid: str | None,
) -> x509.Certificate:
    """`apple_oid` None: the self-signed root; INTERMEDIATE_OID: the
    intermediate; anything else: the leaf."""
    root = apple_oid is None
    ca = root or apple_oid == INTERMEDIATE_OID
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.BasicConstraints(
                ca=ca, path_length=0 if apple_oid == INTERMEDIATE_OID else None
            ),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=not ca,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=ca,
                crl_sign=ca,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
    )
    if not root:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False,
        ).add_extension(
            # DER NULL, as Apple's.
            x509.UnrecognizedExtension(x509.ObjectIdentifier(apple_oid), b"\x05\x00"),
            critical=False,
        )
    return builder.sign(issuer_key, hashes.SHA256())


def apple_sign(pki: ApplePki, claims: dict[str, Any]) -> str:
    """A JWS as Apple signs one: ES256, the chain in `x5c`."""
    return jwt.encode(claims, pki.leaf_key, algorithm="ES256", headers={"x5c": pki.x5c})


def apple_ms(value: datetime) -> int:
    """Apple's dates: milliseconds since the epoch."""
    return int(value.timestamp() * 1000)


def transaction_claims(
    external_id: str,
    user_id: uuid.UUID | str | None,
    environment: str = "Sandbox",
    expires: datetime | None = None,
    product: str = PRODUCT_ID,
    started: datetime | None = None,
) -> dict[str, Any]:
    """A subscription's transaction as Apple signs it, bearing `user_id` as
    its token (none when None)."""
    now = sessions.utc_now()
    claims: dict[str, Any] = {
        "transactionId": f"{external_id}9",
        "originalTransactionId": external_id,
        "bundleId": BUNDLE_ID,
        "productId": product,
        "type": "Auto-Renewable Subscription",
        "purchaseDate": apple_ms(now),
        "originalPurchaseDate": apple_ms(started or now),
        "expiresDate": apple_ms(expires or now + timedelta(days=365)),
        "environment": environment,
        "signedDate": apple_ms(now),
        "inAppOwnershipType": "PURCHASED",
    }
    if user_id is not None:
        claims["appAccountToken"] = str(user_id)
    return claims


def renewal_claims(
    external_id: str,
    environment: str = "Sandbox",
    auto_renew: int = 1,
    grace: datetime | None = None,
    product: str = PRODUCT_ID,
) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "originalTransactionId": external_id,
        "productId": product,
        "autoRenewProductId": product,
        "autoRenewStatus": auto_renew,
        "environment": environment,
        "signedDate": apple_ms(sessions.utc_now()),
    }
    if grace is not None:
        claims["gracePeriodExpiresDate"] = apple_ms(grace)
    return claims


def notification_claims(
    signed_transaction: str, environment: str = "Sandbox", status: int = 1
) -> dict[str, Any]:
    """An App Store Server Notification V2 pointing at a transaction."""
    return {
        "notificationType": "DID_RENEW",
        "notificationUUID": str(uuid.uuid4()),
        "version": "2.0",
        "signedDate": apple_ms(sessions.utc_now()),
        "data": {
            "environment": environment,
            "bundleId": BUNDLE_ID,
            "appAppleId": APP_APPLE_ID,
            "signedTransactionInfo": signed_transaction,
            "status": status,
        },
    }


class FakeApple:
    """Stands in for `app.state.apple_gateway`, an AppleGateway: verification
    runs for real, against `pki`'s root; Apple's API answers from
    `subscriptions`. Records every API call in `calls`; a name in `failures`
    raises that exception; `on_call` runs inside each call, for the
    concurrency tests."""

    def __init__(self, pki: ApplePki, environments: tuple[str, ...]) -> None:
        self.pki = pki
        self.signed = SignedData(
            [pki.root_der], BUNDLE_ID, APP_APPLE_ID, environments, online_checks=False
        )
        self.subscriptions: dict[str, AppleSubscription] = {}
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

    def transaction(self, signed: str) -> dict[str, Any]:
        return self.signed.transaction(signed)

    def notification(self, signed: str) -> dict[str, Any]:
        return self.signed.notification(signed)

    def subscription(self, external_id: str, environment: str) -> AppleSubscription:
        # Read before `on_call`: a read that stalls has the state of its start.
        answer = copy.deepcopy(self.subscriptions.get(external_id))
        self._called("subscription", external_id, environment)
        if answer is None or answer.transaction.get("environment") != environment:
            raise MissingAtApple()
        return answer

    def add(
        self,
        external_id: str,
        user_id: uuid.UUID | str | None,
        status: int = 1,
        environment: str = "Sandbox",
        auto_renew: int = 1,
        expires: datetime | None = None,
        grace: datetime | None = None,
        product: str = PRODUCT_ID,
        started: datetime | None = None,
    ) -> AppleSubscription:
        """The subscription as Apple's API will answer it."""
        subscription = AppleSubscription(
            status,
            transaction_claims(
                external_id, user_id, environment, expires, product, started
            ),
            renewal_claims(external_id, environment, auto_renew, grace, product),
        )
        self.subscriptions[external_id] = subscription
        return subscription

    def signed_transaction(self, external_id: str, **changes: Any) -> str:
        """The stored subscription's latest transaction, signed as StoreKit
        hands it to the app, with `changes` to its claims."""
        claims = self.subscriptions[external_id].transaction | changes
        return apple_sign(self.pki, claims)

    def signed_notification(self, external_id: str, **changes: Any) -> str:
        """A notification pointing at the stored subscription, with `changes`
        to its claims."""
        subscription = self.subscriptions[external_id]
        claims = notification_claims(
            apple_sign(self.pki, subscription.transaction),
            subscription.transaction["environment"],
            subscription.status or 0,
        )
        return apple_sign(self.pki, claims | changes)
