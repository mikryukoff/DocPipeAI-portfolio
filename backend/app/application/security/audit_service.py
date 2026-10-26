from __future__ import annotations

from loguru import logger

from backend.app.infrastructure.repositories.audit_repository import AuditRepository


class AuditService:
    def __init__(self, repo: AuditRepository):
        self.repo = repo

    async def log(self, *, user_id: int | None, action: str, details: dict | None = None) -> None:
        safe_details = details or {}
        await self.repo.create(user_id=user_id, action=action, details=safe_details)
        logger.bind(user_id=user_id, action=action, details=safe_details).info("Security audit event")
