"""Add year to pipelines

Revision ID: b8c9d0e1f2a3
Revises: f7b9c1d2e3a4
Create Date: 2026-05-04

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "f7b9c1d2e3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pipelines", sa.Column("year", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipelines", "year")
