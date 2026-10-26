from enum import Enum
from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy import String, Integer, JSON, ForeignKey

from backend.app.infrastructure.db.database import Base


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class JobORM(Base):
    __tablename__ = "jobs"

    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.PENDING)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0..100
    error: Mapped[str | None] = mapped_column(String(255))

    extra: Mapped[dict] = mapped_column(JSON, nullable=True)