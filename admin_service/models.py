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


class HomegraphStaleness(BaseModel):
    profile_last_updated_at: str | None = None
    is_stale: bool


class HomegraphContextContent(BaseModel):
    summary_short: str
    facts_high_confidence: list[str]
    recent_relevant: list[str]
    uncertain_points: list[str]


class AdminHomegraphContextResponse(BaseModel):
    ok: bool = True
    viewer_id: str
    generated_at: str
    source: str
    staleness: HomegraphStaleness
    context: HomegraphContextContent
    text_block: str


class HomegraphGraphMeta(BaseModel):
    root_node_id: str
    center_node_id: str | None = None
    filtered_by_viewer: bool
    profile_last_updated_at: str | None = None
    max_depth: int | None = None
    truncated: bool | None = None
    stable_node_kinds: list[str]
    stable_link_kinds: list[str]
    filters_applied: dict[str, Any] | None = None


class HomegraphGraphStats(BaseModel):
    node_count: int
    link_count: int
    node_kinds: dict[str, int]
    link_kinds: dict[str, int]


class HomegraphGraphNode(BaseModel):
    id: str
    label: str
    kind: str
    color: str | None = None
    detail: str | None = None


class HomegraphGraphLink(BaseModel):
    source: str
    target: str
    kind: str
    label: str | None = None
    color: str | None = None
    weight: float | None = None
    detail: str | None = None


class AdminHomegraphGraphResponse(BaseModel):
    ok: bool = True
    viewer_id: str | None = None
    generated_at: str
    source: str
    meta: HomegraphGraphMeta
    stats: HomegraphGraphStats
    nodes: list[HomegraphGraphNode]
    links: list[HomegraphGraphLink]


class AdminHomegraphEnrichmentFact(BaseModel):
    fact_id: str | None = None
    kind: str
    value: str
    confidence: float | None = None
    status: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    source_memory_ids: list[str] = Field(default_factory=list)
    source_excerpt: str | None = None
    last_reviewed_at: str | None = None
    review_state: str | None = None

    @field_validator("kind", "value")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        return _normalize_non_empty(str(value)[:MAX_TEXT_CHARS], "value")


class AdminHomegraphEnrichmentRelation(BaseModel):
    relation_id: str | None = None
    target_type: str
    target_id_or_value: str
    relation_type: str
    confidence: float | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    source_memory_ids: list[str] = Field(default_factory=list)

    @field_validator("target_type", "target_id_or_value", "relation_type")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        return _normalize_non_empty(str(value)[:MAX_TEXT_CHARS], "value")


class AdminHomegraphEnrichmentLink(BaseModel):
    link_id: str | None = None
    target_type: str
    target_value: str
    relation_type: str
    target_entity_id: str | None = None
    strength: float | None = None
    confidence: float | None = None
    status: str | None = None
    polarity: str | None = None
    source_memory_ids: list[str] = Field(default_factory=list)
    source_excerpt: str | None = None
    aliases: list[str] = Field(default_factory=list)
    entity_status: str | None = None

    @field_validator("target_type", "target_value", "relation_type")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        return _normalize_non_empty(str(value)[:MAX_TEXT_CHARS], "value")


class AdminHomegraphEnrichmentRequest(BaseModel):
    viewer_id: str
    channel: str | None = None
    viewer_login: str | None = None
    display_name: str | None = None
    summary_short: str | None = None
    summary_long: str | None = None
    facts: list[AdminHomegraphEnrichmentFact] = Field(default_factory=list)
    relations: list[AdminHomegraphEnrichmentRelation] = Field(default_factory=list)
    links: list[AdminHomegraphEnrichmentLink] = Field(default_factory=list)
    conflicts: list[Any] = Field(default_factory=list)
    needs_human_review: list[Any] = Field(default_factory=list)
    model_name: str | None = None
    source_ref: str | None = None

    @field_validator("viewer_id")
    @classmethod
    def validate_viewer_id(cls, value: str) -> str:
        return _normalize_non_empty(str(value)[:MAX_TEXT_CHARS], "viewer_id")


class HomegraphMergeCounts(BaseModel):
    facts: int
    relations: int
    links: int


class AdminHomegraphEnrichmentResponse(BaseModel):
    ok: bool = True
    viewer_id: str
    generated_at: str
    source: str
    dry_run: bool = False
    merged: HomegraphMergeCounts
    context: HomegraphContextContent
    text_block: str
    graph_stats: HomegraphGraphStats


class AdminHomegraphEnrichmentValidationResponse(BaseModel):
    ok: bool = True
    viewer_id: str
    source: str = "homegraph_enrichment_validation_v1"
    mergeable: bool
    counts: HomegraphMergeCounts
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
