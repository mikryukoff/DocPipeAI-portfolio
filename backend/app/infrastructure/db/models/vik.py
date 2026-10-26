from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.infrastructure.db.database import Base


class VikORM(Base):
    __tablename__ = "vik_entries"
    __table_args__ = (
        UniqueConstraint(
            "pipeline_id",
            "statement_text",
            "type",
            name="uq_vik_pipeline_statement_type",
        ),
    )

    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        index=True,
    )
    pipe_num: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    statement_text: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="ВИК")

    pipeline = relationship("PipelineORM", back_populates="vik_entries")
