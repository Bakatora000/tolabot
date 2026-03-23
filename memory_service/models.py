from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_TEXT_CHARS = 1_000
MAX_QUERY_CHARS = 500
MAX_METADATA_ITEMS = 32


def _normalize_non_empty(value: str, field_name: str) -> str:
    normalized = " ".join((value or "").split()).strip()
    if not normalized:
        raise ValueError(f"Field '{field_name}' is required.")
    return normalized


class SearchRequest(BaseModel):
    user_id: str
    query: str
    limit: int | None = None

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        return _normalize_non_empty(value, "user_id")

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = _normalize_non_empty(value[:MAX_QUERY_CHARS], "query")
        return normalized


class RememberRequest(BaseModel):
    user_id: str
    text: str
    metadata: dict[str, Any] | None = None

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        return _normalize_non_empty(value, "user_id")

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = _normalize_non_empty(value[:MAX_TEXT_CHARS], "text")
        return normalized

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if len(value) > MAX_METADATA_ITEMS:
            raise ValueError("Field 'metadata' is too large.")
        return value


class ForgetRequest(BaseModel):
    user_id: str
    memory_id: str

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        return _normalize_non_empty(value, "user_id")

    @field_validator("memory_id")
    @classmethod
    def validate_memory_id(cls, value: str) -> str:
        return _normalize_non_empty(value, "memory_id")


class RecentRequest(BaseModel):
    user_id: str
    limit: int | None = None

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        return _normalize_non_empty(value, "user_id")


class SearchResult(BaseModel):
    id: str
    score: float
    memory: str


class SearchResponse(BaseModel):
    ok: bool = True
    results: list[SearchResult]


class RememberResponse(BaseModel):
    ok: bool = True
    id: str | None = None


class ForgetResponse(BaseModel):
    ok: bool = True
    deleted: bool


class RecentResult(BaseModel):
    id: str
    memory: str
    created_at: str


class RecentResponse(BaseModel):
    ok: bool = True
    results: list[RecentResult]


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "mem0-api"


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str
    detail: str | None = None


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    user_id: str
    memory: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    score: float = 1.0
