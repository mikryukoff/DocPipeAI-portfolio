from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from backend.app.api.dependencies import get_checklist_repository, require_roles
from backend.app.api.schemas.checklist import (
    AdminCreateChecklistItemRequest,
    AdminCreateChecklistItemResponse,
    AdminUpdateChecklistItemRequest,
    AdminUpdateChecklistItemResponse,
    ChecklistItemDoneRequest,
    ChecklistItemResponse,
    ChecklistListResponse,
)
from backend.app.application.exceptions import NotFoundError, ValidationError
from backend.app.infrastructure.db.models.user import UserORM, UserRole
from backend.app.infrastructure.repositories.checklist_repository import ChecklistRepository

user_router = APIRouter(prefix="/checklist", tags=["Checklist"])
admin_checklist_router = APIRouter(prefix="/admin/checklist", tags=["Checklist"])


@user_router.get("", response_model=ChecklistListResponse)
async def list_checklist(
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
    repo: ChecklistRepository = Depends(get_checklist_repository),
):
    items = await repo.list_items_ordered()
    done_ids = await repo.done_item_ids_for_user(current_user.id)
    return ChecklistListResponse(
        items=[
            ChecklistItemResponse(
                id=row.id,
                title=row.title,
                sort_order=row.sort_order,
                done=row.id in done_ids,
            )
            for row in items
        ]
    )


@user_router.put("/items/{item_id}/done")
async def set_checklist_item_done(
    payload: ChecklistItemDoneRequest,
    item_id: int = Path(..., gt=0),
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
    repo: ChecklistRepository = Depends(get_checklist_repository),
):
    item = await repo.get_item_by_id(item_id)
    if item is None:
        raise NotFoundError("Checklist item not found")
    await repo.set_item_done(user_id=current_user.id, item_id=item_id, done=payload.done)
    await repo.session.commit()
    return {"ok": True}


@user_router.post("/reset")
async def reset_checklist_progress(
    current_user: UserORM = Depends(require_roles([UserRole.ADMIN, UserRole.ENGINEER, UserRole.DEMO])),
    repo: ChecklistRepository = Depends(get_checklist_repository),
):
    await repo.reset_progress_for_user(current_user.id)
    await repo.session.commit()
    return {"ok": True}


@admin_checklist_router.post("/items", response_model=AdminCreateChecklistItemResponse)
async def admin_create_checklist_item(
    payload: AdminCreateChecklistItemRequest,
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
    repo: ChecklistRepository = Depends(get_checklist_repository),
):
    title = payload.title.strip()
    if not title:
        raise ValidationError("Title is required")
    if payload.sort_order is not None:
        sort_order = payload.sort_order
    else:
        sort_order = (await repo.max_sort_order()) + 1
    row = await repo.create_item(title=title, sort_order=sort_order)
    await repo.session.commit()
    return AdminCreateChecklistItemResponse(id=row.id, title=row.title, sort_order=row.sort_order)


@admin_checklist_router.delete("/items/{item_id}")
async def admin_delete_checklist_item(
    item_id: int = Path(..., gt=0),
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
    repo: ChecklistRepository = Depends(get_checklist_repository),
):
    deleted = await repo.delete_item(item_id)
    if not deleted:
        raise NotFoundError("Checklist item not found")
    await repo.session.commit()
    return {"ok": True}


@admin_checklist_router.put("/items/{item_id}", response_model=AdminUpdateChecklistItemResponse)
async def admin_update_checklist_item(
    payload: AdminUpdateChecklistItemRequest,
    item_id: int = Path(..., gt=0),
    _: UserORM = Depends(require_roles([UserRole.ADMIN])),
    repo: ChecklistRepository = Depends(get_checklist_repository),
):
    title = payload.title.strip()
    if not title:
        raise ValidationError("Title is required")
    row = await repo.update_item(
        item_id,
        title=title,
        sort_order=payload.sort_order,
    )
    if row is None:
        raise NotFoundError("Checklist item not found")
    await repo.session.commit()
    return AdminUpdateChecklistItemResponse(id=row.id, title=row.title, sort_order=row.sort_order)
