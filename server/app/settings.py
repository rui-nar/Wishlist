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
    # Comma-separated Google OAuth client IDs whose ID tokens sign-in accepts
    # (accounts plan D2). The first is the web client's, which the web build
    # uses and Android passes as its server client ID; /api/config hands it to
    # the clients (D6). Empty: Google sign-in is not configured.
    google_client_ids: str = ""

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
