"""add type column to vik_entries

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-04-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vik_entries",
        sa.Column("type", sa.String(length=32), nullable=False, server_default="ВИК"),
    )
    op.create_index(op.f("ix_vik_entries_type"), "vik_entries", ["type"], unique=False)
    op.drop_constraint("uq_vik_pipeline_statement", "vik_entries", type_="unique")
    op.create_unique_constraint(
        "uq_vik_pipeline_statement_type",
        "vik_entries",
        ["pipeline_id", "statement_text", "type"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_vik_pipeline_statement_type", "vik_entries", type_="unique")
    op.create_unique_constraint(
        "uq_vik_pipeline_statement",
        "vik_entries",
        ["pipeline_id", "statement_text"],
    )
    op.drop_index(op.f("ix_vik_entries_type"), table_name="vik_entries")
    op.drop_column("vik_entries", "type")
