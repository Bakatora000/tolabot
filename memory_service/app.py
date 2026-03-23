from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from memory_service.auth import api_key_dependency
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
