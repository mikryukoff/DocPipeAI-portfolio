from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.infrastructure.db.models.checklist import ChecklistItemORM, UserChecklistProgressORM


class ChecklistRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_items_ordered(self) -> list[ChecklistItemORM]:
        result = await self.session.execute(
            select(ChecklistItemORM).order_by(ChecklistItemORM.sort_order.asc(), ChecklistItemORM.id.asc())
        )
        return list(result.scalars())

    async def get_item_by_id(self, item_id: int) -> ChecklistItemORM | None:
        return await self.session.get(ChecklistItemORM, item_id)

    async def max_sort_order(self) -> int:
        result = await self.session.execute(select(func.coalesce(func.max(ChecklistItemORM.sort_order), -1)))
        return int(result.scalar_one())

    async def create_item(self, *, title: str, sort_order: int) -> ChecklistItemORM:
        row = ChecklistItemORM(title=title, sort_order=sort_order)
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_item(
        self,
        item_id: int,
        *,
        title: str,
        sort_order: int | None = None,
    ) -> ChecklistItemORM | None:
        row = await self.get_item_by_id(item_id)
        if row is None:
            return None
        row.title = title
        if sort_order is not None:
            row.sort_order = sort_order
        await self.session.flush()
        return row

    async def delete_item(self, item_id: int) -> bool:
        row = await self.get_item_by_id(item_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def done_item_ids_for_user(self, user_id: int) -> set[int]:
        result = await self.session.execute(
            select(UserChecklistProgressORM.item_id).where(UserChecklistProgressORM.user_id == user_id)
        )
        return {int(x) for x in result.scalars().all()}

    async def set_item_done(self, *, user_id: int, item_id: int, done: bool) -> None:
        if done:
            existing = await self.session.execute(
                select(UserChecklistProgressORM).where(
                    UserChecklistProgressORM.user_id == user_id,
                    UserChecklistProgressORM.item_id == item_id,
                )
            )
            if existing.scalar_one_or_none() is None:
                self.session.add(UserChecklistProgressORM(user_id=user_id, item_id=item_id))
                await self.session.flush()
        else:
            await self.session.execute(
                delete(UserChecklistProgressORM).where(
                    UserChecklistProgressORM.user_id == user_id,
                    UserChecklistProgressORM.item_id == item_id,
                )
            )

    async def reset_progress_for_user(self, user_id: int) -> None:
        await self.session.execute(delete(UserChecklistProgressORM).where(UserChecklistProgressORM.user_id == user_id))
