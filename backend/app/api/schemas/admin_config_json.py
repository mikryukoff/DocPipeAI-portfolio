from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConfigJsonFileListResponse(BaseModel):
    files: list[str]


class ConfigJsonGetResponse(BaseModel):
    filename: str
    value: Any


class ConfigJsonPutBody(BaseModel):
    value: Any = Field(description="Произвольное JSON-значение (объект, массив, строка и т.д.)")


class ConfigJsonPutResponse(BaseModel):
    filename: str
    ok: bool = True


class SettingsFileEntry(BaseModel):
    """Элемент каталога для UI настроек (русские подписи)."""

    source: str = Field(default="config", description="Источник: каталог конфигурации")
    filename: str
    title_ru: str
    hint_ru: str


class SettingsFileListResponse(BaseModel):
    entries: list[SettingsFileEntry]


class SettingsFileContentResponse(BaseModel):
    source: str
    filename: str
    title_ru: str
    hint_ru: str
    value: Any


class SettingsFilePutResponse(BaseModel):
    source: str
    filename: str
    ok: bool = True
