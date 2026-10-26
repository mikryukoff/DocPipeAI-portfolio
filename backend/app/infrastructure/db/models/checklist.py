from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.infrastructure.db.database import Base


class ChecklistItemORM(Base):
    __tablename__ = "checklist_items"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    progress_rows = relationship(
        "UserChecklistProgressORM",
        back_populates="item",
        cascade="all, delete-orphan",
    )


class UserChecklistProgressORM(Base):
    __tablename__ = "user_checklist_progress"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("checklist_items.id", ondelete="CASCADE"), nullable=False, index=True)

    user = relationship("UserORM", back_populates="checklist_progress")
    item = relationship("ChecklistItemORM", back_populates="progress_rows")

    __table_args__ = (UniqueConstraint("user_id", "item_id", name="uq_user_checklist_item"),)
