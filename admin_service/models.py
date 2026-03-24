from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from memory_service.models import MAX_METADATA_ITEMS, MAX_QUERY_CHARS, MAX_TEXT_CHARS, MemoryRecord, _normalize_non_empty


class AdminHealthResponse(BaseModel):
    status: str = "ok"
    service: str = "mem0-admin-api"


class UserSummary(BaseModel):
    user_id: str
    channel: str | None = None
    viewer: str | None = None


class UserListResponse(BaseModel):
    ok: bool = True
    users: list[UserSummary]


class AdminMemoryResult(BaseModel):
    id: str
    user_id: str
    memory: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    score: float = 1.0

    @classmethod
    def from_record(cls, item: MemoryRecord) -> "AdminMemoryResult":
        return cls(
            id=item.id,
            user_id=item.user_id,
            memory=item.memory,
            metadata=dict(item.metadata or {}),
            created_at=item.created_at,
            updated_at=item.updated_at,
            score=float(item.score),
        )


class AdminRecentResponse(BaseModel):
    ok: bool = True
    results: list[AdminMemoryResult]


class AdminSearchRequest(BaseModel):
    query: str
    limit: int | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        return _normalize_non_empty(value[:MAX_QUERY_CHARS], "query")


class AdminSearchResponse(BaseModel):
    ok: bool = True
    results: list[AdminMemoryResult]


class AdminDeleteMemoryResponse(BaseModel):
    ok: bool = True
    deleted: bool


class AdminPurgeUserResponse(BaseModel):
    ok: bool = True
    user_id: str
    deleted_count: int
    truncated: bool = False


class AdminExportResponse(BaseModel):
    ok: bool = True
    user_id: str
    count: int
    truncated: bool = False
    records: list[AdminMemoryResult]


class AdminImportRecord(BaseModel):
    text: str
    metadata: dict[str, Any] | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _normalize_non_empty(value[:MAX_TEXT_CHARS], "text")

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if len(value) > MAX_METADATA_ITEMS:
            raise ValueError("Field 'metadata' is too large.")
        return value


class AdminImportRequest(BaseModel):
    records: list[AdminImportRecord]


class AdminImportResponse(BaseModel):
    ok: bool = True
    user_id: str
    imported_count: int


class AdminRememberRequest(BaseModel):
    text: str
    metadata: dict[str, Any] | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _normalize_non_empty(value[:MAX_TEXT_CHARS], "text")

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if len(value) > MAX_METADATA_ITEMS:
            raise ValueError("Field 'metadata' is too large.")
        return value


class AdminRememberResponse(BaseModel):
    ok: bool = True
    id: str | None = None
