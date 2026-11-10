"""The audit of admin changes (admin panel plan D4)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AdminAction(Base):
    """One change an admin made. Ids and dates only: never an address."""

    __tablename__ = "admin_actions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # SET NULL: the record outlives the admin's account.
    admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # A fixed word, such as the change's name.
    action: Mapped[str] = mapped_column(String(40))
    # No foreign key: the record outlives the account it changed or deleted.
    target_user_id: Mapped[uuid.UUID]
    # Ids and dates only, as JSON.
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
