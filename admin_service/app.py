from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from admin_service.models import (
    AdminDeleteMemoryResponse,
    AdminExportResponse,
    AdminHealthResponse,
    AdminImportResponse,
    AdminImportRequest,
    AdminMemoryResult,
    AdminPurgeUserResponse,
    AdminRecentResponse,
    AdminRememberRequest,
    AdminRememberResponse,
    AdminSearchRequest,
    AdminSearchResponse,
    UserListResponse,
    UserSummary,
)
from memory_service.auth import admin_key_dependency
from memory_service.backend import MemoryBackendError, build_backend
from memory_service.config import Settings
from memory_service.models import ErrorResponse

settings = Settings.load()
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("admin_service")


def parse_user_parts(user_id: str) -> tuple[str | None, str | None]:
    parts = user_id.split(":")
    if len(parts) >= 4 and parts[0] == "twitch" and parts[2] == "viewer":
        return parts[1] or None, parts[3] or None
    return None, None


def clamp_limit(raw_limit: int | None, settings_obj: Settings) -> int:
    if raw_limit is None:
        return settings_obj.default_limit
    return max(1, min(raw_limit, settings_obj.admin_export_limit))


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.admin_key:
        raise RuntimeError("MEM0_ADMIN_KEY is required.")
    app.state.settings = settings
    app.state.backend = build_backend(settings)
    yield


app = FastAPI(title="mem0-admin-api", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.exception("%s %s status=500 duration_ms=%s", request.method, request.url.path, duration_ms)
        raise

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info("%s %s status=%s duration_ms=%s", request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    detail = exc.errors()[0].get("msg", "Invalid request.") if exc.errors() else "Invalid request."
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=ErrorResponse(error="invalid_request", detail=detail).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error="http_error", detail=str(exc.detail)).model_dump(),
    )


@app.exception_handler(MemoryBackendError)
async def backend_exception_handler(request: Request, exc: MemoryBackendError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=ErrorResponse(error="memory_backend_unavailable", detail=str(exc)).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(error="internal_error").model_dump(),
    )


def backend_dependency(request: Request):
    return request.app.state.backend


admin_auth = [Depends(admin_key_dependency(settings.admin_key))]


@app.get("/health", response_model=AdminHealthResponse)
async def healthcheck():
    return AdminHealthResponse()


@app.get("/users", response_model=UserListResponse, dependencies=admin_auth)
async def list_users(
    channel: str | None = Query(default=None),
    viewer: str | None = Query(default=None),
    backend=Depends(backend_dependency),
):
    requested_channel = (channel or "").strip().lower()
    requested_viewer = (viewer or "").strip().lower()
    users: list[UserSummary] = []
    for user_id in backend.list_user_ids():
        parsed_channel, parsed_viewer = parse_user_parts(user_id)
        if requested_channel and (parsed_channel or "").lower() != requested_channel:
            continue
        if requested_viewer and (parsed_viewer or "").lower() != requested_viewer:
            continue
        users.append(UserSummary(user_id=user_id, channel=parsed_channel, viewer=parsed_viewer))
    users.sort(key=lambda item: item.user_id)
    return UserListResponse(users=users)


@app.get("/users/{user_id}/recent", response_model=AdminRecentResponse, dependencies=admin_auth)
async def recent_user_memories(user_id: str, request: Request, limit: int | None = None, backend=Depends(backend_dependency)):
    effective_limit = clamp_limit(limit, request.app.state.settings)
    results = backend.recent(user_id, effective_limit)
    return AdminRecentResponse(results=[AdminMemoryResult.from_record(item) for item in results])


@app.post("/users/{user_id}/search", response_model=AdminSearchResponse, dependencies=admin_auth)
async def search_user_memories(user_id: str, payload: AdminSearchRequest, request: Request, backend=Depends(backend_dependency)):
    effective_limit = clamp_limit(payload.limit, request.app.state.settings)
    results = backend.search(user_id, payload.query, effective_limit)
    return AdminSearchResponse(results=[AdminMemoryResult.from_record(item) for item in results])


@app.delete("/memories/{memory_id}", response_model=AdminDeleteMemoryResponse, dependencies=admin_auth)
async def delete_memory(memory_id: str, backend=Depends(backend_dependency)):
    deleted = backend.delete_memory(memory_id)
    return AdminDeleteMemoryResponse(deleted=deleted)


@app.delete("/users/{user_id}", response_model=AdminPurgeUserResponse, dependencies=admin_auth)
async def purge_user_memories(user_id: str, request: Request, backend=Depends(backend_dependency)):
    deleted_count, truncated = backend.purge_user(user_id, request.app.state.settings.admin_export_limit)
    return AdminPurgeUserResponse(user_id=user_id, deleted_count=deleted_count, truncated=truncated)


@app.post("/users/{user_id}/export", response_model=AdminExportResponse, dependencies=admin_auth)
async def export_user_memories(user_id: str, request: Request, backend=Depends(backend_dependency)):
    limit = request.app.state.settings.admin_export_limit
    records = backend.export_user(user_id, limit)
    return AdminExportResponse(
        user_id=user_id,
        count=len(records),
        truncated=len(records) >= limit,
        records=[AdminMemoryResult.from_record(item) for item in records],
    )


@app.post("/users/{user_id}/import", response_model=AdminImportResponse, dependencies=admin_auth)
async def import_user_memories(user_id: str, payload: AdminImportRequest, backend=Depends(backend_dependency)):
    imported_count = backend.import_records(
        user_id,
        [{"text": item.text, "metadata": item.metadata or {}} for item in payload.records],
    )
    return AdminImportResponse(user_id=user_id, imported_count=imported_count)


@app.post("/users/{user_id}/remember", response_model=AdminRememberResponse, dependencies=admin_auth)
async def remember_user_memory(user_id: str, payload: AdminRememberRequest, backend=Depends(backend_dependency)):
    memory_id = backend.remember(user_id, payload.text, metadata=payload.metadata)
    return AdminRememberResponse(id=memory_id)
