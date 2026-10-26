from __future__ import annotations

from sqlalchemy import ForeignKey, JSON, String, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.infrastructure.db.database import Base


class SpecItemORM(Base):
    __tablename__ = "spec_items"

    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE")
    )

    pipeline = relationship("PipelineORM", back_populates="spec_items") 

    page: Mapped[str] = mapped_column(String(10))
    section: Mapped[str] = mapped_column(String(255)) 

    position: Mapped[int] = mapped_column(Integer) 
    name: Mapped[str] = mapped_column(String(255)) 
    unit: Mapped[str] = mapped_column(String(10)) 
    quantity: Mapped[float] = mapped_column(Float) 

    extra: Mapped[dict] = mapped_column(JSON)
