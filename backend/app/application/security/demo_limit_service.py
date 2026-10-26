from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.application.exceptions import DemoLimitExceededError
from backend.app.config import Config
from backend.app.infrastructure.db.models.demo_limit import DemoLimitORM
from backend.app.infrastructure.repositories.demo_limit_repository import DemoLimitRepository


class DemoLimitService:
    def __init__(self, repo: DemoLimitRepository, cfg: Config):
        self.repo = repo
        self.cfg = cfg

    async def check_and_increment(self, user_id: int) -> None:
        now = datetime.now(tz=UTC).replace(tzinfo=None)
        row = await self.repo.get_by_user_id(user_id)
        if row is None:
            row = DemoLimitORM(user_id=user_id, download_count=0, period_start=now)
            self.repo.session.add(row)

        period_days = self.cfg.security.demo_period_days
        period_end = row.period_start + timedelta(days=period_days)
        if period_end <= now:
            row.download_count = 0
            row.period_start = now

        if row.download_count >= self.cfg.security.demo_download_limit:
            raise DemoLimitExceededError(
                limit=self.cfg.security.demo_download_limit,
                period_days=period_days,
            )

        row.download_count += 1
        await self.repo.session.flush()
