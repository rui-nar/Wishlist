"""Settings, read from environment variables only (plan D10).

No `.env` file is read here: the dev scripts load it into the environment, and
the compose files pass it with `env_file:`.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


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
    def frontend_origins(self) -> list[str]:
        # A trailing slash would never match the Origin header, which has none.
        return [
            origin.strip().rstrip("/")
            for origin in self.frontend_origin.split(",")
            if origin.strip()
        ]
