from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.app.application.exceptions import DemoLimitExceededError
from backend.app.application.security.demo_limit_service import DemoLimitService
from backend.app.infrastructure.db.models.demo_limit import DemoLimitORM


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


class _FakeRepo:
    def __init__(self, row: DemoLimitORM | None):
        self.row = row
        self.session = _FakeSession()

    async def get_by_user_id(self, _user_id: int):
        return self.row


def _config(limit: int = 2, period_days: int = 7):
    return SimpleNamespace(
        security=SimpleNamespace(
            demo_download_limit=limit,
            demo_period_days=period_days,
        )
    )


@pytest.mark.asyncio
async def test_demo_limit_service_increments_within_limit():
    row = DemoLimitORM(
        user_id=10,
        download_count=1,
        period_start=(datetime.now(tz=UTC) - timedelta(days=1)).replace(tzinfo=None),
    )
    repo = _FakeRepo(row)
    service = DemoLimitService(repo, _config(limit=2))
    await service.check_and_increment(10)
    assert row.download_count == 2


@pytest.mark.asyncio
async def test_demo_limit_service_blocks_on_limit():
    row = DemoLimitORM(
        user_id=11,
        download_count=2,
        period_start=(datetime.now(tz=UTC) - timedelta(days=1)).replace(tzinfo=None),
    )
    repo = _FakeRepo(row)
    service = DemoLimitService(repo, _config(limit=2))
    with pytest.raises(DemoLimitExceededError):
        await service.check_and_increment(11)
