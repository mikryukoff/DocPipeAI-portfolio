from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.db.database import Base


class InstrumentEmbedmentSavedORM(Base):
    """Закладные, перенесённые из удалённого трубопровода (spec_items). Используются в глобальном поиске шаблонов."""

    __tablename__ = "instrument_embedment_saved"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_pipeline_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    extra: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime,
        default=dt.datetime.utcnow,
        nullable=False,
    )
