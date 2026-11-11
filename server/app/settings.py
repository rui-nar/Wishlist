"""Settings, read from environment variables only (plan D10).

No `.env` file is read here: the dev scripts load it into the environment, and
the compose files pass it with `env_file:`.
"""

import contextlib
import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

# ASCII digits, in major units of a two-decimal currency (premium plan D12):
# what Decimal alone would also take, NaN, exponents or a sign, is no price.
_PRICE_AMOUNT = re.compile(r"[0-9]+(\.[0-9]{1,2})?")


class Settings(BaseSettings):
    # SQLAlchemy URL with the psycopg 3 driver:
    # postgresql+psycopg://user:password@host:5432/dbname
    database_url: str
    app_env: Literal["dev", "validation", "production"] = "dev"
    # Set at image build time (v1.2.3 or validation-<short sha>, plan D11).
    app_version: str = "dev"
    # Comma-separated origins allowed by CORS; empty allows none.
    frontend_origin: str = ""
    # Uploaded files (plan D18). The image sets /app/media, where the VPS mounts
    # the directory; locally it is relative to the working directory.
    media_dir: Path = Path("media")
    # Where the nightly dumps are, listed (never read) by the media purge to
    # date the oldest kept dump (gift images plan D9, D10). Unset, the purge
    # does not run: nothing is ever deleted (DEV, VAL).
    backup_dir: Path | None = None
    # Comma-separated Google OAuth client IDs whose ID tokens sign-in accepts
    # (accounts plan D2). The first is the web client's, which the web build
    # uses and Android passes as its server client ID; /api/config hands it to
    # the clients (D6). Empty: Google sign-in is not configured.
    google_client_ids: str = ""
    # Comma-separated Apple client IDs whose identity tokens sign-in accepts
    # (sign-in plan D14). The first is the Services ID, which /api/config hands
    # to the clients (D18). Empty: Apple sign-in is not configured.
    apple_client_ids: str = ""
    # The Android package Apple's callback hands the sign-in to (D16).
    apple_android_package: str = ""
    # Sign the client secret of Apple's token endpoints, which revoking an
    # account's Apple token at its deletion needs (iOS app plan D5). The key is
    # a secret. Any of the three empty: no token is kept or revoked.
    apple_team_id: str = ""
    apple_key_id: str = ""
    apple_private_key: str = ""
    # The origin share links are built on, `<PUBLIC_BASE_URL>/join#<token>`
    # (lists plan D5); /api/config hands it to the mobile apps. Empty in DEV:
    # the web client builds the link on its own origin.
    public_base_url: str = ""
    # Signs the unsubscribe links of emails (comments plan D18); rotating it
    # invalidates every link sent. Empty: every unsubscribe token is refused.
    notification_secret: str = ""
    # Brevo's API key and the sender it knows (comments plan D19). Email is sent
    # only when these, NOTIFICATION_SECRET and PUBLIC_BASE_URL are all set.
    brevo_api_key: str = ""
    email_sender_address: str = ""
    # An empty value, unlike an absent one, means no sender name.
    email_sender_name: str = "Wishlist"
    # Comma-separated. Outside production, the only addresses ever emailed: VAL
    # holds PROD's real addresses (D19). Empty there: nobody is emailed.
    email_allowed_recipients: str = ""
    # False: the worker does not run, and activity waits in the outbox (D16).
    notifications_worker: bool = True
    # Asks for the free plan's limits; they apply only while the app is selling
    # (premium plan D9).
    billing_enforce_limits: bool = False
    free_max_lists: int = Field(default=1, ge=0)
    free_max_gifts_per_list: int = Field(default=20, ge=0)
    # The two secrets make the gateway: webhooks, the portal, cancellation at
    # account deletion. The rest of Stripe's are for selling (D9, D16).
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    stripe_automatic_tax: bool = False
    # The price displayed, a text so that a wrong one withdraws the offer
    # rather than stopping the app (D17). Empty: no offer.
    billing_price_amount: str = ""
    billing_price_currency: str = "EUR"
    # The consent at checkout. Empty outside production: test placeholders; in
    # production: no sale (D16, D17).
    billing_terms_version: str = ""
    billing_consent_text_en: str = ""
    billing_consent_text_fr: str = ""
    # Empty: the client links to its own placeholder pages (D17).
    legal_terms_url: str = ""
    legal_privacy_url: str = ""
    legal_withdrawal_url: str = ""
    # Comma-separated account ids of the admins (admin panel plan D1), never
    # addresses. Empty: no admin, and /api/admin answers 404 to everyone.
    admin_user_ids: str = ""

    @property
    def admin_ids(self) -> frozenset[uuid.UUID]:
        # An entry that is not an id makes no one admin: a typo grants nothing,
        # and does not stop the app.
        ids = set()
        for entry in self.admin_user_ids.split(","):
            with contextlib.suppress(ValueError):
                ids.add(uuid.UUID(entry.strip()))
        return frozenset(ids)

    @property
    def admin_ids_invalid(self) -> list[int]:
        """The positions (from 1, counted between commas) of the entries of
        ADMIN_USER_IDS that are not ids. Never their values: one may be an
        address."""
        positions = []
        for position, entry in enumerate(self.admin_user_ids.split(","), start=1):
            if not entry.strip():
                continue
            try:
                uuid.UUID(entry.strip())
            except ValueError:
                positions.append(position)
        return positions

    @property
    def billing_price(self) -> Decimal | None:
        amount = self.billing_price_amount.strip()
        price = Decimal(amount) if _PRICE_AMOUNT.fullmatch(amount) else None
        # Nothing is sold for nothing: zero is no price either.
        return price or None

    @property
    def missing_gateway_settings(self) -> list[str]:
        """The variables that keep the app from talking to Stripe (D16)."""
        key = self.stripe_secret_key.strip()
        # VAL is seeded from PROD: outside production, a live key could charge
        # the real customers it holds.
        live = key.startswith(("sk_live_", "rk_live_"))
        values = {
            "STRIPE_SECRET_KEY": key if live == (self.app_env == "production") else "",
            "STRIPE_WEBHOOK_SECRET": self.stripe_webhook_secret,
        }
        return [name for name, value in values.items() if not value.strip()]

    @property
    def missing_selling_settings(self) -> list[str]:
        """The variables that keep the app from offering a purchase (D16)."""
        values = {
            "STRIPE_PRICE_ID": self.stripe_price_id,
            "BILLING_PRICE_AMOUNT": "set" if self.billing_price else "",
            "BILLING_PRICE_CURRENCY": self.billing_price_currency,
            "PUBLIC_BASE_URL": self.public_base_url.strip().rstrip("/"),
        }
        if self.app_env == "production":
            # A first real sale needs the EU obligations in place.
            values |= {
                "STRIPE_AUTOMATIC_TAX": "set" if self.stripe_automatic_tax else "",
                "BILLING_TERMS_VERSION": self.billing_terms_version,
                "BILLING_CONSENT_TEXT_EN": self.billing_consent_text_en,
                "BILLING_CONSENT_TEXT_FR": self.billing_consent_text_fr,
                "LEGAL_TERMS_URL": self.legal_terms_url,
                "LEGAL_PRIVACY_URL": self.legal_privacy_url,
                "LEGAL_WITHDRAWAL_URL": self.legal_withdrawal_url,
            }
        return self.missing_gateway_settings + [
            name for name, value in values.items() if not value.strip()
        ]

    @property
    def billing_gateway_configured(self) -> bool:
        return not self.missing_gateway_settings

    @property
    def billing_selling(self) -> bool:
        return not self.missing_selling_settings

    @property
    def limits_enforced(self) -> bool:
        # Nobody can be blocked from growing a list while there is no way to
        # pay (D9).
        return self.billing_enforce_limits and self.billing_selling

    @property
    def missing_email_settings(self) -> list[str]:
        """The variables that keep email off, by the name the operator sets."""
        values = {
            "BREVO_API_KEY": self.brevo_api_key,
            "EMAIL_SENDER_ADDRESS": self.email_sender_address,
            "NOTIFICATION_SECRET": self.notification_secret,
            "PUBLIC_BASE_URL": self.public_base_url.strip().rstrip("/"),
        }
        return [name for name, value in values.items() if not value.strip()]

    @property
    def email_allowed_addresses(self) -> frozenset[str]:
        # Compared whatever the case: Google may report an address differently
        # from how the operator typed it.
        return frozenset(
            address.strip().casefold()
            for address in self.email_allowed_recipients.split(",")
            if address.strip()
        )

    @property
    def google_audiences(self) -> list[str]:
        return [
            client_id.strip()
            for client_id in self.google_client_ids.split(",")
            if client_id.strip()
        ]

    @property
    def apple_audiences(self) -> list[str]:
        return [
            client_id.strip()
            for client_id in self.apple_client_ids.split(",")
            if client_id.strip()
        ]

    @property
    def apple_redirect_uri(self) -> str | None:
        """Where Apple's web flow, on the web and Android, sends its answer
        (sign-in plan D16). Apple's token endpoint wants it again with a code
        from that flow."""
        public_base_url = self.public_base_url.strip().rstrip("/")
        if not public_base_url:
            return None
        return f"{public_base_url}/api/auth/apple/callback"

    @property
    def frontend_origins(self) -> list[str]:
        # A trailing slash would never match the Origin header, which has none.
        return [
            origin.strip().rstrip("/")
            for origin in self.frontend_origin.split(",")
            if origin.strip()
        ]
