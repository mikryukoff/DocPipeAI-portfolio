"""add checklist_items and user_checklist_progress tables

Revision ID: b2c3d4e5f6a7
Revises: 9c1e4a2f7b8d
Create Date: 2026-04-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "9c1e4a2f7b8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "checklist_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "user_checklist_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["checklist_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "item_id", name="uq_user_checklist_item"),
    )
    op.create_index(
        op.f("ix_user_checklist_progress_user_id"),
        "user_checklist_progress",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_checklist_progress_item_id"),
        "user_checklist_progress",
        ["item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_checklist_progress_item_id"), table_name="user_checklist_progress")
    op.drop_index(op.f("ix_user_checklist_progress_user_id"), table_name="user_checklist_progress")
    op.drop_table("user_checklist_progress")
    op.drop_table("checklist_items")
