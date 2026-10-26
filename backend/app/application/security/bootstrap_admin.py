from __future__ import annotations

from loguru import logger
from sqlalchemy import select

from backend.app.config import load_config
from backend.app.infrastructure.db.database import AsyncSessionLocal
from backend.app.infrastructure.db.models.user import UserORM, UserRole
from backend.app.security.passwords import hash_password


async def ensure_admin_user_from_env() -> None:
    cfg = load_config()
    username = (cfg.security.bootstrap_admin_username or "").strip()
    password = cfg.security.bootstrap_admin_password or ""
    if not username or not password:
        logger.warning("Admin bootstrap skipped: BOOTSTRAP_ADMIN_USERNAME/PASSWORD are empty")
        return

    try:
        role = UserRole(cfg.security.bootstrap_admin_role)
    except ValueError:
        logger.warning(
            "Invalid BOOTSTRAP_ADMIN_ROLE='{}', fallback to admin",
            cfg.security.bootstrap_admin_role,
        )
        role = UserRole.ADMIN

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(select(UserORM).where(UserORM.username == username))
            user = result.scalar_one_or_none()
            if user is None:
                user = UserORM(
                    username=username,
                    role=role,
                    password_hash=hash_password(password),
                    temporary_password=None,
                    force_password_change=False,
                    is_active=cfg.security.bootstrap_admin_is_active,
                )
                session.add(user)
                await session.commit()
                logger.info("Bootstrap admin created. username={} role={}", username, role.value)
                return

            user.role = role
            user.is_active = cfg.security.bootstrap_admin_is_active
            user.force_password_change = False
            user.temporary_password = None
            if cfg.security.bootstrap_admin_reset_password_on_start:
                user.password_hash = hash_password(password)
            await session.commit()
            logger.info(
                "Bootstrap admin updated. username={} role={} reset_password_on_start={}",
                username,
                role.value,
                cfg.security.bootstrap_admin_reset_password_on_start,
            )
        except Exception:
            await session.rollback()
            logger.exception("Failed to bootstrap admin user from env")
