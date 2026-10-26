"""Merge alembic heads: pipeline year vs vik/checklist/embedment_saved

Revision ID: a9b8c7d6e5f4
Revises: b8c9d0e1f2a3, d1e2f3a4b5c6
Create Date: 2026-05-04

Объединяет две ветки от f7b9c1d2e3a4 (колонка year и цепочка vik/checklist/instrument_embedment_saved).
"""

from typing import Sequence, Union


revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, Sequence[str], None] = ("b8c9d0e1f2a3", "d1e2f3a4b5c6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
