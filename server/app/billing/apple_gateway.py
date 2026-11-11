"""Apple's App Store, behind one module (Apple IAP plan D3, D4).

The only module that imports Apple's `app-store-server-library`, and lazily:
an environment without the variables never loads it. Apple's signed payloads
are verified against Apple's root certificate, and its answers can be late,
wrong, missing or hostile, so everything leaves here as a plain dict, a small
value or a typed exception: no key, signed payload, token or Apple message
goes into a log line or an exception, only ids, numbers and fixed words.
"""

import logging
from typing import Any

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from app.accounts.apple import load_private_key
from app.billing import apple_events
from app.billing.apple_events import PRODUCTION, SANDBOX, AppleSubscription
from app.settings import Settings

_log = logging.getLogger(__name__)

# Apple Root CA - G3, which signs the App Store's payloads: public, from
# https://www.apple.com/certificateauthority/, as the library's README asks
# ("download and store"). Valid until 2039-04-30. Its SHA-256 fingerprint,
# which test_apple_gateway.py pins:
# 63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179
APPLE_ROOT_CA_G3 = b"""-----BEGIN CERTIFICATE-----
MIICQzCCAcmgAwIBAgIILcX8iNLFS5UwCgYIKoZIzj0EAwMwZzEbMBkGA1UEAwwS
QXBwbGUgUm9vdCBDQSAtIEczMSYwJAYDVQQLDB1BcHBsZSBDZXJ0aWZpY2F0aW9u
IEF1dGhvcml0eTETMBEGA1UECgwKQXBwbGUgSW5jLjELMAkGA1UEBhMCVVMwHhcN
MTQwNDMwMTgxOTA2WhcNMzkwNDMwMTgxOTA2WjBnMRswGQYDVQQDDBJBcHBsZSBS
b290IENBIC0gRzMxJjAkBgNVBAsMHUFwcGxlIENlcnRpZmljYXRpb24gQXV0aG9y
aXR5MRMwEQYDVQQKDApBcHBsZSBJbmMuMQswCQYDVQQGEwJVUzB2MBAGByqGSM49
AgEGBSuBBAAiA2IABJjpLz1AcqTtkyJygRMc3RCV8cWjTnHcFBbZDuWmBSp3ZHtf
TjjTuxxEtX/1H7YyYl3J6YRbTzBPEVoA/VhYDKX1DyxNB0cTddqXl5dvMVztK517
IDvYuVTZXpmkOlEKMaNCMEAwHQYDVR0OBBYEFLuw3qFYM4iapIqZ3r6966/ayySr
MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgEGMAoGCCqGSM49BAMDA2gA
MGUCMQCD6cHEFl4aXTQY2e3v9GwOAEZLuN+yRhHFD/3meoyhpmvOwgPUnPWTxnS4
at+qIxUCMG1mihDK1A3UT82NQz60imOlM27jbdoXt2QfyFMm+YhidDkLF1vLUagM
6BgD56KyKA==
-----END CERTIFICATE-----
"""

# Apple's API error codes for a transaction it does not know.
_NOT_FOUND = frozenset(
    {
        4000006,  # INVALID_TRANSACTION_ID
        4040005,  # ORIGINAL_TRANSACTION_ID_NOT_FOUND
        4040010,  # TRANSACTION_ID_NOT_FOUND
    }
)


class AppleError(Exception):
    """Apple's answer, reduced to its meaning: its text stays out."""


class AppleUnavailable(AppleError):
    """Apple failed, refused or answered something unusable; retrying later is
    safe."""


class MissingAtApple(AppleError):
    """Apple does not know this subscription."""


class InvalidSignedData(Exception):
    """Not a payload signed through Apple's root for this app, in an
    environment accepted here. Why it failed is nobody's business."""


def root_certificates() -> list[bytes]:
    """Apple's root, as the library takes it (DER)."""
    root = x509.load_pem_x509_certificate(APPLE_ROOT_CA_G3)
    return [root.public_bytes(serialization.Encoding.DER)]


class SignedData:
    """Verifies Apple's signed payloads: the chain up to `root_certificates`,
    the app's bundle id, and an environment among `environments` (D6)."""

    def __init__(
        self,
        root_certificates: list[bytes],
        bundle_id: str,
        app_apple_id: int | None,
        environments: tuple[str, ...],
        online_checks: bool,
    ) -> None:
        from appstoreserverlibrary.models.Environment import Environment
        from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier

        self.environments = environments
        # Online: the certificates' revocation is asked of Apple (OCSP), as
        # Apple advises; the tests, which reach no network, check offline.
        self._verifiers = [
            SignedDataVerifier(
                root_certificates,
                online_checks,
                Environment(name),
                bundle_id,
                app_apple_id if name == PRODUCTION else None,
            )
            for name in environments
        ]

    def transaction(self, signed: str) -> dict[str, Any]:
        return self._verified(signed, "verify_and_decode_signed_transaction")

    def renewal(self, signed: str) -> dict[str, Any]:
        return self._verified(signed, "verify_and_decode_renewal_info")

    def notification(self, signed: str) -> dict[str, Any]:
        return self._verified(signed, "verify_and_decode_notification")

    def _verified(self, signed: str, method: str) -> dict[str, Any]:
        """The payload's claims, once one environment's verifier accepts it.
        Each verifier refuses another environment's payload, so each is
        tried in turn."""
        from appstoreserverlibrary.signed_data_verifier import (
            VerificationException,
            VerificationStatus,
        )

        for verifier in self._verifiers:
            try:
                getattr(verifier, method)(signed)
            except VerificationException as exc:
                if exc.status == VerificationStatus.INVALID_ENVIRONMENT:
                    continue
                if exc.status == VerificationStatus.RETRYABLE_VERIFICATION_FAILURE:
                    _log.warning("apple: a certificate's revocation could not be read")
                    raise AppleUnavailable() from None
                raise InvalidSignedData() from None
            except Exception:
                raise InvalidSignedData() from None
            # Plain dicts for the translator: the library's objects are not.
            return jwt.decode(signed, options={"verify_signature": False})
        raise InvalidSignedData()


class AppleGateway:
    """Constructed once, only when selling on iPhone is configured (D7)."""

    def __init__(
        self,
        signed: SignedData,
        bundle_id: str,
        issuer_id: str,
        key_id: str,
        private_key_pem: bytes,
    ) -> None:
        from appstoreserverlibrary.api_client import AppStoreServerAPIClient
        from appstoreserverlibrary.models.Environment import Environment

        self._signed = signed
        # The same key reads both environments.
        self._clients = {
            name: AppStoreServerAPIClient(
                private_key_pem, key_id, issuer_id, bundle_id, Environment(name)
            )
            for name in signed.environments
        }

    def transaction(self, signed: str) -> dict[str, Any]:
        return self._signed.transaction(signed)

    def notification(self, signed: str) -> dict[str, Any]:
        return self._signed.notification(signed)

    def subscription(self, external_id: str, environment: str) -> AppleSubscription:
        """The subscription as Apple has it now, its signed parts verified
        (D3). One call, of at most the library's 30 s."""
        from appstoreserverlibrary.api_client import APIException

        client = self._clients.get(environment)
        # Into a URL path: digits only.
        if client is None or not (external_id.isascii() and external_id.isdigit()):
            raise MissingAtApple()
        try:
            answer = client.get_all_subscription_statuses(external_id)
        except APIException as exc:
            raise _translation(exc.http_status_code, exc.raw_api_error) from None
        except Exception as exc:
            _log.warning("apple: statuses: %s", type(exc).__name__)
            raise AppleUnavailable() from None
        item = next(
            (
                item
                for group in answer.data or []
                for item in group.lastTransactions or []
                if item.originalTransactionId == external_id
            ),
            None,
        )
        if item is None or not item.signedTransactionInfo:
            _log.warning("apple: subscription %s is not in Apple's answer", external_id)
            raise MissingAtApple()
        try:
            transaction = self._signed.transaction(item.signedTransactionInfo)
            renewal = (
                self._signed.renewal(item.signedRenewalInfo)
                if item.signedRenewalInfo
                else {}
            )
        except InvalidSignedData:
            _log.error(
                "apple: subscription %s: Apple's answer failed its signature check",
                external_id,
            )
            raise AppleUnavailable() from None
        if (
            apple_events.environment(transaction) != environment
            or apple_events.original_transaction_id(transaction) != external_id
        ):
            _log.error(
                "apple: subscription %s: Apple answered for another", external_id
            )
            raise AppleUnavailable()
        return AppleSubscription(item.rawStatus, transaction, renewal)


def _translation(http_status: int, api_error: int | None) -> AppleError:
    if api_error in _NOT_FOUND:
        _log.warning("apple: statuses: not found (%s)", api_error)
        return MissingAtApple()
    if http_status == 401:
        # Not a blip: nothing works until the key is fixed.
        _log.error("apple: statuses: the In-App Purchase key was refused (401)")
    else:
        _log.warning("apple: statuses: HTTP %s, error %s", http_status, api_error)
    return AppleUnavailable()


def from_settings(settings: Settings) -> tuple[AppleGateway | None, list[str]]:
    """The gateway, or None and the variables that keep selling on iPhone off,
    missing or unloadable, by the name the operator sets. Never a value: the
    key is a secret."""
    gaps = list(settings.missing_apple_settings)
    text = settings.apple_iap_private_key
    key = load_private_key(text) if text.strip() else None
    if text.strip() and key is None:
        gaps.append("APPLE_IAP_PRIVATE_KEY")
    if gaps or key is None:
        return None, gaps
    production = settings.app_env == "production"
    bundle_id = settings.apple_bundle_id.strip()
    signed = SignedData(
        root_certificates(),
        bundle_id,
        int(settings.apple_app_apple_id.strip()) if production else None,
        # D6: production takes Sandbox purchases too, from listed accounts
        # only, which the routes check; elsewhere, Sandbox only.
        (PRODUCTION, SANDBOX) if production else (SANDBOX,),
        online_checks=True,
    )
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    gateway = AppleGateway(
        signed,
        bundle_id,
        settings.apple_iap_issuer_id.strip(),
        settings.apple_iap_key_id.strip(),
        pem,
    )
    return gateway, []
