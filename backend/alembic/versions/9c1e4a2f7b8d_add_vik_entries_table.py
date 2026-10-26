"""add vik_entries table

Revision ID: 9c1e4a2f7b8d
Revises: f7b9c1d2e3a4
Create Date: 2026-04-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9c1e4a2f7b8d"
down_revision: Union[str, Sequence[str], None] = "f7b9c1d2e3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vik_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("pipeline_id", sa.Integer(), nullable=False),
        sa.Column("pipe_num", sa.String(length=255), nullable=False),
        sa.Column("statement_text", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pipeline_id",
            "statement_text",
            name="uq_vik_pipeline_statement",
        ),
    )
    op.create_index(
        op.f("ix_vik_entries_pipeline_id"),
        "vik_entries",
        ["pipeline_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_vik_entries_pipe_num"),
        "vik_entries",
        ["pipe_num"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_vik_entries_pipe_num"), table_name="vik_entries")
    op.drop_index(op.f("ix_vik_entries_pipeline_id"), table_name="vik_entries")
    op.drop_table("vik_entries")
