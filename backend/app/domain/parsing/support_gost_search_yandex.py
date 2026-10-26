from __future__ import annotations

import asyncio
import os
import re
import threading
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yandex_ai_studio_sdk import AsyncAIStudio

from backend.app.domain.parsing.support_gost_mapping_store import SupportGostMappingStore
from backend.app.infrastructure.db.database import AsyncSessionLocal
from backend.app.infrastructure.db.models.spec_item import SpecItemORM
from backend.app.shared.parsing_audit_logger import log_parsing_event

_GOST_RE = re.compile(
    r"\bГОСТ\s*(?:Р\s*)?\d+(?:\.\d+)?(?:\s*[-–]\s*\d+){0,3}\b",
    re.IGNORECASE,
)
_VALID_GOST_RE = re.compile(r"^ГОСТ(?:\s+Р)?\s+\d{1,6}(?:\.\d+)*-\d{2,4}$", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


def _extract_gost(text: str) -> str:
    match = _GOST_RE.search(text or "")
    if not match:
        return ""
    value = _SPACE_RE.sub(" ", match.group(0).upper().replace("–", "-")).strip()
    if "-" not in value:
        digits = re.sub(r"\D", "", value.removeprefix("ГОСТ "))
        if len(digits) == 7:
            return f"ГОСТ {digits[:-2]}-{digits[-2:]}"
    return value


def _is_valid_gost_candidate(gost: str) -> bool:
    return bool(_VALID_GOST_RE.match((gost or "").strip()))


def _extract_model_tokens(search_name: str) -> list[str]:
    return [
        token.replace(" ", "")
        for token in re.findall(
            r"(опх\d+|опс-о|опб|пху|пг|вп(?:-\d+)?|то\s*\(3d\))",
            (search_name or "").lower(),
            flags=re.IGNORECASE,
        )
    ]


def _score_gost_context(context: str, model_tokens: list[str]) -> int:
    context_l = (context or "").lower()
    score = 0
    if "гост" in context_l:
        score += 2
    if any(term in context_l for term in ("опора", "подвес", "трубопровод")):
        score += 2
    if model_tokens and any(t in context_l.replace(" ", "") for t in model_tokens):
        score += 3
    return score


def _normalize_api_key(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if value.lower().startswith("api-key "):
        return value.split(" ", 1)[1].strip()
    return value


def _normalize_family_query_text(name: str) -> str:
    family = _build_family_key(name)
    return family.title() if family else ""


def _pick_best_gost_from_docs(docs: list[Any], model_tokens: list[str]) -> tuple[int, str] | None:
    best: tuple[int, str] | None = None
    for doc in docs:
        source_text = " ".join(
            x
            for x in (
                (doc.title or "").strip(),
                " ".join(doc.passages or ()).strip(),
                (getattr(doc, "url", "") or "").strip(),
            )
            if x
        ).strip()
        candidate = _extract_gost(source_text)
        if not candidate or not _is_valid_gost_candidate(candidate):
            continue
        score = _score_gost_context(source_text, model_tokens)
        if best is None or score > best[0]:
            best = (score, candidate)
    return best


def _build_family_key(name: str) -> str:
    value = (name or "").strip().upper()
    model_match = re.search(r"\b(ОПС-О|ОПХ\d+|ОПП\d+|ОПН\d+)\b", value)
    if model_match:
        left = re.sub(r"[^A-ZА-ЯЁ0-9]+", " ", value[: model_match.start()]).strip()
        model = model_match.group(1).replace("-", " ")
        return re.sub(r"\s+", " ", f"{left} {model}".strip())
    value = re.sub(r"\b\d+[.,]?\d*(?:-\d+[.,]?\d*)+\b", " ", value)
    value = re.sub(r"\b(?:09Г2С|20|СТ20|AISI\s*\d+)\b", " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", re.sub(r"[-,./]+", " ", value)).strip()


def _audit(audit_ctx: dict[str, Any] | None, *, field: str, value: Any, note: str, status: str = "parsed") -> None:
    if not audit_ctx:
        return
    try:
        log_parsing_event(
            job_id=audit_ctx.get("job_id"),
            user_log_key=audit_ctx.get("user_log_key"),
            source_type=audit_ctx.get("source_type", "other"),
            source_file=audit_ctx.get("source_file", "unknown"),
            parser="SupportGostSearch",
            entity="support",
            entity_id=audit_ctx.get("pipeline_name"),
            field=field,
            value=value,
            status=status,
            note=note,
            origin={
                "page": audit_ctx.get("page"),
                "row_text": audit_ctx.get("row_text"),
                "support_name": audit_ctx.get("support_name"),
                "position": audit_ctx.get("position"),
            },
        )
    except Exception:
        pass


async def _save_gost_to_db(*, support_name: str, gost: str, session: AsyncSession) -> int:
    result = await session.execute(
        select(SpecItemORM).where(SpecItemORM.section == "supports", SpecItemORM.name == support_name)
    )
    rows = list(result.scalars().all())
    for row in rows:
        extra = dict(row.extra or {})
        extra["gost"] = gost
        row.extra = extra
    await session.flush()
    return len(rows)


async def search_gost(gost_name: str, session: Optional[AsyncSession] = None) -> dict | None:
    name = (gost_name or "").strip()
    if not name:
        return None

    folder_id = (os.getenv("YANDEX_FOLDER_ID") or "").strip()
    api_key = _normalize_api_key(os.getenv("YANDEX_API_KEY"))
    if not folder_id or not api_key:
        logger.warning("Missing Yandex credentials: YANDEX_FOLDER_ID / YANDEX_API_KEY")
        return None

    query = f"{name} какой ГОСТ"
    fallback_query = ""
    family_query = _normalize_family_query_text(name)
    if family_query and family_query.lower() != name.lower():
        fallback_query = f"{family_query} какой ГОСТ"
    model_tokens = _extract_model_tokens(name)
    sdk = AsyncAIStudio(folder_id=folder_id, auth=api_key)
    search = sdk.search_api.web(search_type="RU")
    queries = [query] + ([fallback_query] if fallback_query else [])
    best: tuple[int, str] | None = None
    used_query = query
    for current_query in queries:
        try:
            response = await search.run(query=current_query, format="parsed", timeout=45)
        except Exception as exc:
            logger.warning("Yandex Search API request failed. query='{}' error='{}'", current_query, exc)
            continue
        best = _pick_best_gost_from_docs(list(response.docs), model_tokens=model_tokens)
        if best:
            used_query = current_query
            break

    if best is None:
        return None

    gost = best[1]
    store = SupportGostMappingStore()
    family_key = _build_family_key(name)
    store.set_exact(name, gost)
    store.set_family(family_key, gost)

    updated_rows = 0
    try:
        if session is None:
            async with AsyncSessionLocal() as db_session:
                updated_rows = await _save_gost_to_db(support_name=name, gost=gost, session=db_session)
                await db_session.commit()
        else:
            updated_rows = await _save_gost_to_db(support_name=name, gost=gost, session=session)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Support GOST DB save failed. name='{}' gost='{}' error='{}'",
            name,
            gost,
            exc,
        )

    return {
        "name": name,
        "query": used_query,
        "gost": gost,
        "source": "yandex_search_api",
        "updated_rows": updated_rows,
    }


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, Exception] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            error["exc"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "exc" in error:
        raise error["exc"]
    return result.get("value")


class SupportGostSearch:
    def __init__(self, enabled: bool = False, timeout_sec: float = 45.0, log_enabled: bool = True, mapping_store: SupportGostMappingStore | None = None) -> None:
        self.enabled = enabled
        self.timeout_sec = timeout_sec
        self.log_enabled = log_enabled
        self.mapping_store = mapping_store or SupportGostMappingStore()
        self._cache: dict[str, str] = {}
        self._family_cache: dict[str, str] = {}

    @classmethod
    def from_env(cls) -> "SupportGostSearch":
        return cls(
            enabled=_env_bool("SUPPORT_GOST_SEARCH_ENABLED", default=True),
            timeout_sec=_env_float("SUPPORT_GOST_SEARCH_TIMEOUT_SEC", default=45.0),
            log_enabled=_env_bool("SUPPORT_GOST_SEARCH_LOG_ENABLED", default=True),
        )

    def find_gost(self, support_name: str, audit_ctx: dict[str, Any] | None = None) -> str:
        search_name = (support_name or "").strip()
        if not self.enabled or not search_name:
            return ""

        if search_name in self._cache:
            return self._cache[search_name]

        stored_exact = self.mapping_store.get_exact(search_name)
        if stored_exact:
            self._cache[search_name] = stored_exact
            return stored_exact
        stored_exact_relaxed = self.mapping_store.get_exact_relaxed(search_name)
        if stored_exact_relaxed:
            self._cache[search_name] = stored_exact_relaxed
            return stored_exact_relaxed

        family_key = _build_family_key(search_name)
        if family_key in self._family_cache:
            value = self._family_cache[family_key]
            self._cache[search_name] = value
            return value

        stored_family = self.mapping_store.get_family(family_key)
        if stored_family:
            self._family_cache[family_key] = stored_family
            self._cache[search_name] = stored_family
            return stored_family
        stored_family_relaxed = self.mapping_store.get_family_relaxed(family_key)
        if stored_family_relaxed:
            self._family_cache[family_key] = stored_family_relaxed
            self._cache[search_name] = stored_family_relaxed
            return stored_family_relaxed

        _audit(audit_ctx, field="gost_search", value=f"{search_name} какой ГОСТ", note="search_started_yandex_api")
        try:
            payload = _run_coro_sync(search_gost(search_name))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Support GOST Yandex search failed. name='{}' error='{}'", search_name, exc)
            _audit(audit_ctx, field="gost_search_result", value="", note=f"yandex_api_error: {exc}", status="warning")
            return ""

        if payload and isinstance(payload, dict):
            gost = str(payload.get("gost", "")).strip()
            if gost:
                self._cache[search_name] = gost
                self._family_cache[family_key] = gost
                self.mapping_store.set_exact(search_name, gost)
                self.mapping_store.set_family(family_key, gost)
                _audit(audit_ctx, field="gost_search_result", value=gost, note="found_yandex_api")
                return gost

        _audit(audit_ctx, field="gost_search_result", value="", note="not_found_yandex_api", status="warning")
        return ""

    @staticmethod
    def _build_family_key(name: str) -> str:
        return _build_family_key(name)

    @staticmethod
    def _extract_gost(text: str) -> str:
        return _extract_gost(text)

    @staticmethod
    def _is_valid_gost_candidate(gost: str) -> bool:
        return _is_valid_gost_candidate(gost)

    @staticmethod
    def _extract_model_tokens(search_name: str) -> list[str]:
        return _extract_model_tokens(search_name)

    @staticmethod
    def _score_gost_context(context: str, model_tokens: list[str]) -> int:
        return _score_gost_context(context, model_tokens)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
