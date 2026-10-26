from __future__ import annotations

from pydantic import BaseModel, Field


class ChecklistItemResponse(BaseModel):
    id: int
    title: str
    sort_order: int
    done: bool


class ChecklistListResponse(BaseModel):
    items: list[ChecklistItemResponse]


class ChecklistItemDoneRequest(BaseModel):
    done: bool


class AdminCreateChecklistItemRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    sort_order: int | None = None


class AdminCreateChecklistItemResponse(BaseModel):
    id: int
    title: str
    sort_order: int


class AdminUpdateChecklistItemRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    sort_order: int | None = None


class AdminUpdateChecklistItemResponse(BaseModel):
    id: int
    title: str
    sort_order: int
