"""gift images

Images, the orphan files the purge remembers, and a gift's image (gift images
plan D2). New tables and a nullable column the previous release ignores, so it
keeps working against it (DevOps plan D15).

Revision ID: 655e9747d91f
Revises: efc657e64bf8
Create Date: 2026-11-08 18:10:36.076913

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "655e9747d91f"
down_revision: str | Sequence[str] | None = "efc657e64bf8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_orphans",
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_media_orphans")),
    )
    op.create_table(
        "images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attached_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_images_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_images")),
    )
    op.create_index(
        op.f("ix_images_uploaded_by"), "images", ["uploaded_by"], unique=False
    )
    op.add_column("gifts", sa.Column("image_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(op.f("uq_gifts_image_id"), "gifts", ["image_id"])
    op.create_foreign_key(
        op.f("fk_gifts_image_id_images"), "gifts", "images", ["image_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_gifts_image_id_images"), "gifts", type_="foreignkey")
    op.drop_constraint(op.f("uq_gifts_image_id"), "gifts", type_="unique")
    op.drop_column("gifts", "image_id")
    op.drop_index(op.f("ix_images_uploaded_by"), table_name="images")
    op.drop_table("images")
    op.drop_table("media_orphans")
