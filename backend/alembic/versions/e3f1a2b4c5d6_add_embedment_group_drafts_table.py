"""add embedment_group_drafts table

Revision ID: e3f1a2b4c5d6
Revises: c2d4e8f0a1b3
Create Date: 2026-04-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f1a2b4c5d6"
down_revision: Union[str, Sequence[str], None] = "c2d4e8f0a1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "embedment_group_drafts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("pipeline_id", sa.Integer(), nullable=False),
        sa.Column("dedup_key", sa.String(length=512), nullable=False),
        sa.Column("embedment_group_key", sa.String(length=255), nullable=False),
        sa.Column("drawing_image_path", sa.String(length=512), nullable=True),
        sa.Column("peer_tags", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pipeline_id",
            "dedup_key",
            name="uq_embedment_draft_pipeline_dedup",
        ),
    )
    op.create_index(
        op.f("ix_embedment_group_drafts_pipeline_id"),
        "embedment_group_drafts",
        ["pipeline_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_embedment_group_drafts_pipeline_id"),
        table_name="embedment_group_drafts",
    )
    op.drop_table("embedment_group_drafts")
