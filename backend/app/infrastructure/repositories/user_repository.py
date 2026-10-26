from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.infrastructure.db.models.user import UserORM


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_username(self, username: str) -> UserORM | None:
        result = await self.session.execute(select(UserORM).where(UserORM.username == username))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> UserORM | None:
        return await self.session.get(UserORM, user_id)

    async def list_users(self) -> list[UserORM]:
        result = await self.session.execute(select(UserORM).order_by(UserORM.id.asc()))
        return list(result.scalars())
