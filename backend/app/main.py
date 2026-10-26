from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.exception_handlers import register_exception_handlers
from backend.app.api.routers.admin import router as admin_router
from backend.app.api.routers.admin_config_json import router as admin_config_json_router
from backend.app.api.routers.auth import router as auth_router
from backend.app.api.routers.checklist import admin_checklist_router, user_router as checklist_user_router
from backend.app.api.routers.ocr import router as ocr_router
from backend.app.api.routers.pipelines import router as pipelines_router
from backend.app.application.security.bootstrap_admin import ensure_admin_user_from_env
from backend.app.shared.logging_config import get_structured_logger, setup_logger

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logger()
    slog = get_structured_logger()
    await ensure_admin_user_from_env()
    slog.logger.info("App startup completed. frontend_dir={}", FRONTEND_DIR)

    yield

    slog.logger.info("App shutdown")


app = FastAPI(title="Pipeline Passport API", lifespan=lifespan)


def _is_frontend_static_path(path: str) -> bool:
    if path in {"/", "/index.html"}:
        return True
    if path.startswith("/js/") or path.startswith("/css/"):
        return True
    return path.endswith(".html")


@app.middleware("http")
async def frontend_cache_control_middleware(request, call_next):
    response = await call_next(request)
    if request.method in {"GET", "HEAD"} and _is_frontend_static_path(request.url.path):
        # Force browser to revalidate frontend assets on regular reload.
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def structured_logging_middleware(request, call_next):
    middleware = getattr(app.state, "_structured_logging_middleware", None)
    if middleware is None:
        middleware = get_structured_logger().make_middleware()
        app.state._structured_logging_middleware = middleware
    return await middleware(request, call_next)


register_exception_handlers(app)


@app.get("/favicon.svg")
async def favicon_svg():
    """Иконка вкладки: явный маршрут + no-store, иначе браузер долго держит старый кэш."""
    path = FRONTEND_DIR / "favicon.svg"
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(
        path,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/favicon.ico")
async def favicon_ico():
    """Многие клиенты запрашивают /favicon.ico; отдаём тот же SVG (современные ОК с image/svg+xml)."""
    path = FRONTEND_DIR / "favicon.svg"
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(
        path,
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


# 1. Маршруты API — всегда первыми
app.include_router(pipelines_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_config_json_router)
app.include_router(checklist_user_router)
app.include_router(admin_checklist_router)
app.include_router(ocr_router)

# 2. Статика по явным путям
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")

# 3. Главная статика (HTML) — последней
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
