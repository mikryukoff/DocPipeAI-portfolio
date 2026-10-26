from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from backend.app.infrastructure.repositories.pipeline_repository import PipelineRepository


def pipeline_repo_factory(
    session_factory: async_sessionmaker[AsyncSession],
):
    @asynccontextmanager
    async def _factory():
        async with session_factory() as session:
            repo = PipelineRepository(session)
            try:
                yield repo
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _factory