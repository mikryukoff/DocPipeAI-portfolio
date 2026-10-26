from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.infrastructure.db.models.audit_log import AuditLogORM


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, user_id: int | None, action: str, details: dict | None = None) -> AuditLogORM:
        row = AuditLogORM(
            user_id=user_id,
            action=action,
            details=details or {},
            timestamp=datetime.now(tz=UTC).replace(tzinfo=None),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_recent(self, *, limit: int = 100) -> list[AuditLogORM]:
        result = await self.session.execute(
            select(AuditLogORM).order_by(AuditLogORM.timestamp.desc()).limit(limit)
        )
        return list(result.scalars())

    async def list_filtered(
        self,
        *,
        user_id: int | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLogORM]:
        stmt = select(AuditLogORM)
        if user_id is not None:
            stmt = stmt.where(AuditLogORM.user_id == user_id)
        if action:
            stmt = stmt.where(AuditLogORM.action.ilike(f"%{action.strip()}%"))
        if date_from is not None:
            stmt = stmt.where(AuditLogORM.timestamp >= date_from)
        if date_to is not None:
            stmt = stmt.where(AuditLogORM.timestamp <= date_to)
        stmt = stmt.order_by(AuditLogORM.timestamp.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def clear_filtered(
        self,
        *,
        user_id: int | None = None,
    ) -> int:
        stmt = delete(AuditLogORM)
        if user_id is not None:
            stmt = stmt.where(AuditLogORM.user_id == user_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return int(result.rowcount or 0)
