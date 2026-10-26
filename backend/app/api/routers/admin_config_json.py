from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from loguru import logger

from backend.app.api.dependencies import get_audit_service, get_config, require_roles
from backend.app.api.schemas.admin_config_json import (
    ConfigJsonFileListResponse,
    ConfigJsonGetResponse,
    ConfigJsonPutBody,
    ConfigJsonPutResponse,
    SettingsFileContentResponse,
    SettingsFileEntry,
    SettingsFileListResponse,
    SettingsFilePutResponse,
)
from backend.app.application.exceptions import NotFoundError, ValidationError
from backend.app.application.security.audit_service import AuditService
from backend.app.config import Config
from backend.app.domain.parsing.armature_gost_store import reset_armature_gost_store
from backend.app.infrastructure.db.models.user import UserORM, UserRole

router = APIRouter(prefix="/admin", tags=["Admin"])

_CONFIG_JSON_FILENAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*\.json$")
_CONFIG_JSON_MAX_BYTES = 5 * 1024 * 1024

# Русские подписи для известных файлов data/config
_CONFIG_FILE_META: dict[str, tuple[str, str]] = {
    "armature_gost.json": (
        "Сопоставление ГОСТ/ТУ для арматуры",
        "Фрагмент наименования из спецификации → ГОСТ или ТУ.",
    ),
    "support_gost_mapping.json": (
        "Сопоставление ГОСТ для опор",
        "Точные названия и семейства опор — по разделам ниже.",
    ),
    "spec_item_sections.json": (
        "Разделы строк спецификации",
        "Позиция или наименование → таблица паспорта (4.1–4.4). В JSON по-прежнему хранятся разделы. "
        "Для 4.1 и 4.3 раздел выводится из первого слова ключа (Труба/Трубы и Опора/Опоры), как при импорте. "
        "Устаревшие или нестандартные значения в файле можно заменить, выбрав таблицу.",
    ),
}


def _config_dir(cfg: Config) -> Path:
    return Path(cfg.user_data.config_path)


def _meta_config(filename: str) -> tuple[str, str]:
    if filename in _CONFIG_FILE_META:
        return _CONFIG_FILE_META[filename]
    return (
        f"Файл «{filename}»",
        "Произвольные данные в формате JSON.",
    )


def _load_json_value(path: Path, *, filename: str) -> Any:
    if not path.is_file():
        raise NotFoundError("Config file not found")
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in settings file. path={} err={}", path, e)
        raise ValidationError(
            "File is not valid JSON",
            details={"reason": "invalid_json", "filename": filename},
        ) from e


def _validate_config_filename(name: str) -> str:
    raw = (name or "").strip()
    if not raw or not _CONFIG_JSON_FILENAME_RE.fullmatch(raw):
        raise ValidationError(
            "Invalid config filename",
            details={"reason": "invalid_config_filename", "filename": raw},
        )
    return raw


def _resolve_config_file(cfg: Config, filename: str) -> Path:
    filename = _validate_config_filename(filename)
    base = _config_dir(cfg).resolve()
    target = (base / filename).resolve()
    if target.parent != base:
        raise ValidationError(
            "Invalid config path",
            details={"reason": "path_escape", "filename": filename},
        )
    return target


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    payload = text.encode("utf-8")
    if len(payload) > _CONFIG_JSON_MAX_BYTES:
        raise ValidationError(
            "JSON payload too large",
            details={
                "reason": "config_json_too_large",
                "max_bytes": _CONFIG_JSON_MAX_BYTES,
            },
        )
    fd, tmp_path = tempfile.mkstemp(
        prefix=".cfg_json_",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@router.get("/config-json", response_model=ConfigJsonFileListResponse)
async def list_config_json_files(
    _: Annotated[UserORM, Depends(require_roles([UserRole.ADMIN]))],
    config: Config = Depends(get_config),
):
    base = _config_dir(config)
    base.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for p in sorted(base.iterdir()):
        if p.is_file() and p.suffix.lower() == ".json":
            names.append(p.name)
    return ConfigJsonFileListResponse(files=names)


@router.get("/config-json/{filename}", response_model=ConfigJsonGetResponse)
async def get_config_json_file(
    filename: str,
    _: Annotated[UserORM, Depends(require_roles([UserRole.ADMIN]))],
    config: Config = Depends(get_config),
):
    path = _resolve_config_file(config, filename)
    if not path.is_file():
        raise NotFoundError("Config file not found")
    value = _load_json_value(path, filename=filename)
    return ConfigJsonGetResponse(filename=path.name, value=value)


@router.put("/config-json/{filename}", response_model=ConfigJsonPutResponse)
async def put_config_json_file(
    filename: str,
    body: ConfigJsonPutBody,
    admin: Annotated[UserORM, Depends(require_roles([UserRole.ADMIN]))],
    config: Config = Depends(get_config),
    audit: AuditService = Depends(get_audit_service),
):
    path = _resolve_config_file(config, filename)
    payload = json.dumps(body.value, ensure_ascii=False).encode("utf-8")
    if len(payload) > _CONFIG_JSON_MAX_BYTES:
        raise ValidationError(
            "JSON payload too large",
            details={
                "reason": "config_json_too_large",
                "max_bytes": _CONFIG_JSON_MAX_BYTES,
            },
        )
    _atomic_write_json(path, body.value)
    if filename == "armature_gost.json":
        reset_armature_gost_store()
    await audit.log(
        user_id=admin.id,
        action="admin_config_json_updated",
        details={"filename": filename},
    )
    logger.info("Config JSON updated. filename={} user_id={}", filename, admin.id)
    return ConfigJsonPutResponse(filename=filename, ok=True)


_SETTINGS_FILES_ROLES: list[UserRole] = [UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO]


@router.get("/settings-files", response_model=SettingsFileListResponse)
async def list_settings_files(
    _: Annotated[UserORM, Depends(require_roles(_SETTINGS_FILES_ROLES))],
    config: Config = Depends(get_config),
):
    """Каталог JSON в каталоге конфигурации приложения."""
    entries: list[SettingsFileEntry] = []

    cfg_base = _config_dir(config)
    cfg_base.mkdir(parents=True, exist_ok=True)
    for p in sorted(cfg_base.iterdir()):
        if p.is_file() and p.suffix.lower() == ".json":
            title, hint = _meta_config(p.name)
            entries.append(
                SettingsFileEntry(
                    source="config",
                    filename=p.name,
                    title_ru=title,
                    hint_ru=hint,
                )
            )

    return SettingsFileListResponse(entries=entries)


@router.get("/settings-files/content", response_model=SettingsFileContentResponse)
async def get_settings_file_content(
    _: Annotated[UserORM, Depends(require_roles(_SETTINGS_FILES_ROLES))],
    config: Config = Depends(get_config),
    filename: str = Query(description="Имя файла .json в каталоге конфигурации"),
):
    path = _resolve_config_file(config, filename)
    title, hint = _meta_config(path.name)
    value = _load_json_value(path, filename=filename)
    return SettingsFileContentResponse(
        source="config",
        filename=path.name,
        title_ru=title,
        hint_ru=hint,
        value=value,
    )


@router.put("/settings-files/content", response_model=SettingsFilePutResponse)
async def put_settings_file_content(
    admin: Annotated[UserORM, Depends(require_roles(_SETTINGS_FILES_ROLES))],
    body: ConfigJsonPutBody,
    config: Config = Depends(get_config),
    audit: AuditService = Depends(get_audit_service),
    filename: str = Query(description="Имя файла .json в каталоге конфигурации"),
):
    payload = json.dumps(body.value, ensure_ascii=False).encode("utf-8")
    if len(payload) > _CONFIG_JSON_MAX_BYTES:
        raise ValidationError(
            "JSON payload too large",
            details={
                "reason": "config_json_too_large",
                "max_bytes": _CONFIG_JSON_MAX_BYTES,
            },
        )
    path = _resolve_config_file(config, filename)
    _atomic_write_json(path, body.value)
    if path.name == "armature_gost.json":
        reset_armature_gost_store()

    await audit.log(
        user_id=admin.id,
        action="admin_settings_file_updated",
        details={"source": "config", "filename": path.name},
    )
    logger.info(
        "Settings file updated. filename={} user_id={}",
        path.name,
        admin.id,
    )
    return SettingsFilePutResponse(source="config", filename=path.name, ok=True)
