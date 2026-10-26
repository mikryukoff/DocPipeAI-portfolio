from __future__ import annotations

from sqlalchemy import String, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.infrastructure.db.models.spec_item import SpecItemORM
from backend.app.infrastructure.db.models.vik import VikORM
from backend.app.infrastructure.db.database import Base

class PipelineORM(Base):
    __tablename__ = "pipelines"

    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    medium: Mapped[str] = mapped_column(String(255))

    mounting_scheme: Mapped[str | None] = mapped_column(String(255))

    year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    flow_direction: Mapped[dict] = mapped_column(JSON)
    parameters: Mapped[dict] = mapped_column(JSON)
    pipelines_len: Mapped[dict] = mapped_column(JSON)
    last_import_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    spec_items: Mapped[list["SpecItemORM"]] = relationship(
        back_populates="pipeline",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    vik_entries: Mapped[list["VikORM"]] = relationship(
        back_populates="pipeline",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="VikORM.id",
    )
