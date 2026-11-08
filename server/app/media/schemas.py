"""Response bodies of the image endpoints (gift images plan D11)."""

import uuid

from pydantic import BaseModel


class ImageOut(BaseModel):
    """An image and where to read it. The server writes the paths (D7), so a
    later change of routes needs no client change."""

    id: uuid.UUID
    # Of the full version.
    width: int
    height: int
    url: str
    thumb_url: str
