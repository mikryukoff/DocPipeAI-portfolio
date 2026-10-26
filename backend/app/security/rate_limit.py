from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.app.application.exceptions import TooManyRequestsError
from backend.app.config import Config


@dataclass
class LoginLimiterState:
    attempts: deque[datetime]
    blocked_until: datetime | None = None


class LoginRateLimiter:
    def __init__(self):
        self._state: dict[str, LoginLimiterState] = defaultdict(
            lambda: LoginLimiterState(attempts=deque())
        )

    def _now(self) -> datetime:
        return datetime.now(tz=UTC)

    def check(self, *, ip: str, cfg: Config) -> None:
        state = self._state[ip]
        now = self._now()
        if state.blocked_until and state.blocked_until > now:
            raise TooManyRequestsError("Too many login attempts. Try again later.")

        window_start = now - timedelta(minutes=cfg.security.login_window_min)
        while state.attempts and state.attempts[0] < window_start:
            state.attempts.popleft()

    def mark_failure(self, *, ip: str, cfg: Config) -> None:
        state = self._state[ip]
        now = self._now()
        state.attempts.append(now)
        if len(state.attempts) >= cfg.security.login_attempts_limit:
            state.blocked_until = now + timedelta(minutes=cfg.security.login_block_min)

    def mark_success(self, *, ip: str) -> None:
        state = self._state[ip]
        state.attempts.clear()
        state.blocked_until = None


login_rate_limiter = LoginRateLimiter()
