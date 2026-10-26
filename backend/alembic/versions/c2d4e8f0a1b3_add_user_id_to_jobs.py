"""Add user_id to jobs

Revision ID: c2d4e8f0a1b3
Revises: a1f5cb71f8c2
Create Date: 2026-04-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2d4e8f0a1b3"
down_revision: Union[str, Sequence[str], None] = "a1f5cb71f8c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_jobs_user_id_users",
        "jobs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_jobs_user_id_users", "jobs", type_="foreignkey")
    op.drop_column("jobs", "user_id")
