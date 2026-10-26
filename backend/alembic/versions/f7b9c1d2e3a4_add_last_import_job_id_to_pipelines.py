"""Add last_import_job_id to pipelines

Revision ID: f7b9c1d2e3a4
Revises: e3f1a2b4c5d6
Create Date: 2026-04-09

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7b9c1d2e3a4"
down_revision: Union[str, Sequence[str], None] = "e3f1a2b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pipelines", sa.Column("last_import_job_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipelines", "last_import_job_id")
