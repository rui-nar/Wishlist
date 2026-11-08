"""Request and response bodies of the image endpoints (gift images plan D11)."""

import uuid

from pydantic import BaseModel, ConfigDict


class ImageFromUrl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Checked by the fetcher, which answers url_not_allowed for anything it
    # refuses, a URL too long included (D6).
    url: str


class ImageOut(BaseModel):
    """An image and where to read it. The server writes the paths (D7), so a
    later change of routes needs no client change."""

    id: uuid.UUID
    # Of the full version.
    width: int
    height: int
    url: str
    thumb_url: str
