from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from admin_service.models import (
    AdminDeleteMemoryResponse,
    AdminExportResponse,
    AdminHomegraphGraphResponse,
    AdminHealthResponse,
    AdminHomegraphContextResponse,
    AdminImportRequest,
    AdminImportResponse,
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
from homegraph.context import build_viewer_context_payload
from homegraph.graph import build_viewer_graph_payload
from homegraph.multihop_graph import build_multihop_graph_payload
from memory_service.auth import admin_key_dependency, api_key_dependency
from memory_service.backend import MemoryBackendError, build_backend
from memory_service.config import Settings
from memory_service.models import (
    ErrorResponse,
    ForgetRequest,
    ForgetResponse,
    HealthResponse,
    RecentRequest,
    RecentResponse,
    RecentResult,
    RememberRequest,
    RememberResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)

settings = Settings.load()
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("memory_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.api_key:
        raise RuntimeError("MEM0_API_KEY is required.")
    app.state.settings = settings
    app.state.backend = build_backend(settings)
    yield


app = FastAPI(title="mem0-api", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    user_id = "-"
    try:
        if request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if body:
                try:
                    import json

                    payload = json.loads(body.decode("utf-8"))
                    user_id = str(payload.get("user_id", "-"))
                except Exception:
                    user_id = "-"
    except Exception:
        user_id = "-"

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.exception("%s %s status=500 duration_ms=%s user_id=%s", request.method, request.url.path, duration_ms, user_id)
        raise

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "%s %s status=%s duration_ms=%s user_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        user_id,
    )
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


def clamp_limit(raw_limit: int | None, settings_obj: Settings) -> int:
    if raw_limit is None:
        return settings_obj.default_limit
    return max(1, min(raw_limit, settings_obj.max_limit))


def clamp_admin_limit(raw_limit: int | None, settings_obj: Settings) -> int:
    if raw_limit is None:
        return settings_obj.default_limit
    return max(1, min(raw_limit, settings_obj.admin_export_limit))


def parse_user_parts(user_id: str) -> tuple[str | None, str | None]:
    parts = user_id.split(":")
    if len(parts) >= 4 and parts[0] == "twitch" and parts[2] == "viewer":
        return parts[1] or None, parts[3] or None
    return None, None


def is_test_user_id(user_id: str) -> bool:
    channel, viewer = parse_user_parts(user_id)
    channel_value = (channel or "").lower()
    viewer_value = (viewer or "").lower()
    if channel_value == "integration":
        return True
    return viewer_value.startswith("windows_linux_e2e_")


def admin_local_only_dependency(request: Request) -> None:
    if request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"ok": False, "error": "admin_local_only"},
        )


def admin_auth_dependencies(expected_key: str):
    return [
        Depends(admin_key_dependency(expected_key)),
        Depends(admin_local_only_dependency),
    ]


@app.get("/health", response_model=HealthResponse)
async def healthcheck():
    return HealthResponse()


@app.post("/search", response_model=SearchResponse, dependencies=[Depends(api_key_dependency(settings.api_key))])
async def search_memory(payload: SearchRequest, request: Request, backend=Depends(backend_dependency)):
    limit = clamp_limit(payload.limit, request.app.state.settings)
    results = backend.search(payload.user_id, payload.query, limit)
    return SearchResponse(
        results=[
            SearchResult(id=item.id, score=float(item.score), memory=item.memory)
            for item in results
        ]
    )


@app.post("/remember", response_model=RememberResponse, dependencies=[Depends(api_key_dependency(settings.api_key))])
async def remember_memory(payload: RememberRequest, backend=Depends(backend_dependency)):
    memory_id = backend.remember(payload.user_id, payload.text, metadata=payload.metadata)
    return RememberResponse(id=memory_id)


@app.post("/forget", response_model=ForgetResponse, dependencies=[Depends(api_key_dependency(settings.api_key))])
async def forget_memory(payload: ForgetRequest, backend=Depends(backend_dependency)):
    deleted = backend.forget(payload.user_id, payload.memory_id)
    return ForgetResponse(deleted=deleted)


@app.post("/recent", response_model=RecentResponse, dependencies=[Depends(api_key_dependency(settings.api_key))])
async def recent_memory(payload: RecentRequest, request: Request, backend=Depends(backend_dependency)):
    limit = clamp_limit(payload.limit, request.app.state.settings)
    results = backend.recent(payload.user_id, limit)
    return RecentResponse(
        results=[
            RecentResult(id=item.id, memory=item.memory, created_at=item.created_at)
            for item in results
        ]
    )


@app.get("/admin/health", response_model=AdminHealthResponse)
async def admin_healthcheck():
    return AdminHealthResponse()


@app.get("/admin/users", response_model=UserListResponse, dependencies=admin_auth_dependencies(settings.admin_key))
async def admin_list_users(
    channel: str | None = None,
    viewer: str | None = None,
    include_test_users: bool = False,
    backend=Depends(backend_dependency),
):
    requested_channel = (channel or "").strip().lower()
    requested_viewer = (viewer or "").strip().lower()
    users: list[UserSummary] = []
    for user_id in backend.list_user_ids():
        if not include_test_users and is_test_user_id(user_id):
            continue
        parsed_channel, parsed_viewer = parse_user_parts(user_id)
        if requested_channel and (parsed_channel or "").lower() != requested_channel:
            continue
        if requested_viewer and (parsed_viewer or "").lower() != requested_viewer:
            continue
        users.append(UserSummary(user_id=user_id, channel=parsed_channel, viewer=parsed_viewer))
    users.sort(key=lambda item: item.user_id)
    return UserListResponse(users=users)


@app.get("/admin/users/{user_id}/recent", response_model=AdminRecentResponse, dependencies=admin_auth_dependencies(settings.admin_key))
async def admin_recent_user_memories(user_id: str, request: Request, limit: int | None = None, backend=Depends(backend_dependency)):
    effective_limit = clamp_admin_limit(limit, request.app.state.settings)
    results = backend.recent(user_id, effective_limit)
    return AdminRecentResponse(results=[AdminMemoryResult.from_record(item) for item in results])


@app.post("/admin/users/{user_id}/search", response_model=AdminSearchResponse, dependencies=admin_auth_dependencies(settings.admin_key))
async def admin_search_user_memories(user_id: str, payload: AdminSearchRequest, request: Request, backend=Depends(backend_dependency)):
    effective_limit = clamp_admin_limit(payload.limit, request.app.state.settings)
    results = backend.search(user_id, payload.query, effective_limit)
    return AdminSearchResponse(results=[AdminMemoryResult.from_record(item) for item in results])


@app.delete("/admin/memories/{memory_id}", response_model=AdminDeleteMemoryResponse, dependencies=admin_auth_dependencies(settings.admin_key))
async def admin_delete_memory(memory_id: str, backend=Depends(backend_dependency)):
    deleted = backend.delete_memory(memory_id)
    return AdminDeleteMemoryResponse(deleted=deleted)


@app.delete("/admin/users/{user_id}", response_model=AdminPurgeUserResponse, dependencies=admin_auth_dependencies(settings.admin_key))
async def admin_purge_user_memories(user_id: str, request: Request, backend=Depends(backend_dependency)):
    deleted_count, truncated = backend.purge_user(user_id, request.app.state.settings.admin_export_limit)
    return AdminPurgeUserResponse(user_id=user_id, deleted_count=deleted_count, truncated=truncated)


@app.post("/admin/users/{user_id}/export", response_model=AdminExportResponse, dependencies=admin_auth_dependencies(settings.admin_key))
async def admin_export_user_memories(user_id: str, request: Request, backend=Depends(backend_dependency)):
    limit = request.app.state.settings.admin_export_limit
    records = backend.export_user(user_id, limit)
    return AdminExportResponse(
        user_id=user_id,
        count=len(records),
        truncated=len(records) >= limit,
        records=[AdminMemoryResult.from_record(item) for item in records],
    )


@app.post("/admin/users/{user_id}/import", response_model=AdminImportResponse, dependencies=admin_auth_dependencies(settings.admin_key))
async def admin_import_user_memories(user_id: str, payload: AdminImportRequest, backend=Depends(backend_dependency)):
    imported_count = backend.import_records(
        user_id,
        [{"text": item.text, "metadata": item.metadata or {}} for item in payload.records],
    )
    return AdminImportResponse(user_id=user_id, imported_count=imported_count)


@app.post("/admin/users/{user_id}/remember", response_model=AdminRememberResponse, dependencies=admin_auth_dependencies(settings.admin_key))
async def admin_remember_user_memory(user_id: str, payload: AdminRememberRequest, backend=Depends(backend_dependency)):
    memory_id = backend.remember(user_id, payload.text, metadata=payload.metadata)
    return AdminRememberResponse(id=memory_id)


@app.get(
    "/admin/homegraph/users/{user_id}/context",
    response_model=AdminHomegraphContextResponse,
    dependencies=admin_auth_dependencies(settings.admin_key),
)
async def admin_homegraph_viewer_context(user_id: str, request: Request):
    settings_obj = getattr(request.app.state, "settings", settings)
    payload = build_viewer_context_payload(
        viewer_id=user_id,
        db_path=settings_obj.homegraph_db_path,
    )
    return AdminHomegraphContextResponse(**payload)


@app.get(
    "/admin/homegraph/users/{user_id}/graph",
    response_model=AdminHomegraphGraphResponse,
    dependencies=admin_auth_dependencies(settings.admin_key),
)
async def admin_homegraph_viewer_graph(
    user_id: str,
    request: Request,
    include_uncertain: bool = True,
    min_weight: float | None = None,
    max_links: int | None = None,
):
    settings_obj = getattr(request.app.state, "settings", settings)
    payload = build_viewer_graph_payload(
        viewer_id=user_id,
        db_path=settings_obj.homegraph_db_path,
        include_uncertain=include_uncertain,
        min_weight=min_weight,
        max_links=max_links,
    )
    return AdminHomegraphGraphResponse(**payload)


@app.get(
    "/admin/homegraph/graph",
    response_model=AdminHomegraphGraphResponse,
    dependencies=admin_auth_dependencies(settings.admin_key),
)
async def admin_homegraph_multihop_graph(
    request: Request,
    center_node_id: str,
    max_depth: int = 1,
    max_nodes: int | None = None,
    max_links: int | None = None,
    include_uncertain: bool = True,
    min_weight: float | None = None,
):
    settings_obj = getattr(request.app.state, "settings", settings)
    payload = build_multihop_graph_payload(
        center_node_id=center_node_id,
        db_path=settings_obj.homegraph_db_path,
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_links=max_links,
        include_uncertain=include_uncertain,
        min_weight=min_weight,
    )
    return AdminHomegraphGraphResponse(**payload)
