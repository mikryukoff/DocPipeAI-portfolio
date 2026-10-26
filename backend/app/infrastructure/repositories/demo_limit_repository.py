from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.infrastructure.db.models.demo_limit import DemoLimitORM


class DemoLimitRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: int) -> DemoLimitORM | None:
        result = await self.session.execute(select(DemoLimitORM).where(DemoLimitORM.user_id == user_id))
        return result.scalar_one_or_none()
