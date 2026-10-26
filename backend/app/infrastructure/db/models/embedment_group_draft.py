from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.db.database import Base


class EmbedmentGroupDraftORM(Base):
    """Черновик данных закладной по группе (path или ключ): подтягивается к новым spec_items (aliases)."""

    __tablename__ = "embedment_group_drafts"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "dedup_key", name="uq_embedment_draft_pipeline_dedup"),
    )

    pipeline_id: Mapped[int] = mapped_column(
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dedup_key: Mapped[str] = mapped_column(String(512), nullable=False)
    embedment_group_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    drawing_image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    peer_tags: Mapped[list] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime,
        default=dt.datetime.utcnow,
        onupdate=dt.datetime.utcnow,
        nullable=False,
    )
