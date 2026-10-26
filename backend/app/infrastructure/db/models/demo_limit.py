from __future__ import annotations

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.infrastructure.db.database import Base


class DemoLimitORM(Base):
    __tablename__ = "demo_limits"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    download_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    period_start: Mapped[DateTime] = mapped_column(DateTime, nullable=False)

    user = relationship("UserORM", back_populates="demo_limit")
