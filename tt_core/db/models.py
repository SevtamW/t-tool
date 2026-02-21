from __future__ import annotations

from sqlmodel import Field, SQLModel
from sqlalchemy import Index


class SchemaMeta(SQLModel, table=True):
    __tablename__ = "schema_meta"

    key: str = Field(primary_key=True)
    value: str


class Project(SQLModel, table=True):
    __tablename__ = "projects"
    __table_args__ = (Index("idx_projects_slug_unique", "slug", unique=True),)

    id: str = Field(primary_key=True)
    name: str
    slug: str
    default_source_locale: str
    default_target_locale: str
    created_at: str
    updated_at: str


class ProjectLocale(SQLModel, table=True):
    __tablename__ = "project_locales"
    __table_args__ = (
        Index(
            "idx_project_locales_project_locale",
            "project_id",
            "locale_code",
            unique=True,
        ),
    )

    id: str = Field(primary_key=True)
    project_id: str
    locale_code: str
    is_enabled: int
    is_default: int
    rules_json: str = Field(default="{}")


class Asset(SQLModel, table=True):
    __tablename__ = "assets"
    __table_args__ = (Index("idx_assets_project_received_at", "project_id", "received_at"),)

    id: str = Field(primary_key=True)
    project_id: str
    asset_type: str
    original_name: str | None = None
    source_channel: str = Field(default="manual")
    received_at: str
    content_hash: str | None = None
    storage_path: str | None = None
    size_bytes: int | None = None


class SchemaProfile(SQLModel, table=True):
    __tablename__ = "schema_profiles"
    __table_args__ = (
        Index(
            "idx_schema_profiles_project_signature",
            "project_id",
            "signature",
            unique=True,
        ),
    )

    id: str = Field(primary_key=True)
    project_id: str
    signature: str
    mapping_json: str
    confidence: float = Field(default=0.0)
    confirmed_by_user: int = Field(default=0)
    created_at: str
    updated_at: str


class Segment(SQLModel, table=True):
    __tablename__ = "segments"
    __table_args__ = (Index("idx_segments_asset_row_index", "asset_id", "row_index"),)

    id: str = Field(primary_key=True)
    asset_id: str
    sheet_name: str | None = None
    row_index: int | None = None
    key: str | None = None
    source_locale: str
    source_text: str
    cn_text: str | None = None
    context_json: str = Field(default="{}")
    char_limit: int | None = None
    placeholders_json: str = Field(default="[]")


class TranslationCandidate(SQLModel, table=True):
    __tablename__ = "translation_candidates"
    __table_args__ = (
        Index(
            "idx_translation_candidates_segment_target",
            "segment_id",
            "target_locale",
        ),
    )

    id: str = Field(primary_key=True)
    segment_id: str
    target_locale: str
    candidate_text: str
    candidate_type: str
    score: float = Field(default=0.0)
    model_info_json: str = Field(default="{}")
    generated_at: str


class ApprovedTranslation(SQLModel, table=True):
    __tablename__ = "approved_translations"
    __table_args__ = (
        Index(
            "idx_approved_translations_segment_target",
            "segment_id",
            "target_locale",
            unique=True,
        ),
    )

    id: str = Field(primary_key=True)
    segment_id: str
    target_locale: str
    final_text: str
    status: str = Field(default="approved")
    approved_by: str | None = None
    approved_at: str
    revision_of_id: str | None = None
    is_pinned: int = Field(default=0)


class TMEntry(SQLModel, table=True):
    __tablename__ = "tm_entries"
    __table_args__ = (
        Index(
            "idx_tm_entries_lookup",
            "project_id",
            "source_locale",
            "target_locale",
            "normalized_source_hash",
        ),
    )

    id: str = Field(primary_key=True)
    project_id: str
    source_locale: str
    target_locale: str
    source_text: str
    target_text: str
    normalized_source_hash: str
    origin: str
    origin_asset_id: str | None = None
    origin_row_ref: str | None = None
    created_at: str
    updated_at: str
    last_used_at: str | None = None
    use_count: int = Field(default=0)
    quality_tag: str = Field(default="trusted")


class GlossaryTerm(SQLModel, table=True):
    __tablename__ = "glossary_terms"
    __table_args__ = (
        Index(
            "idx_glossary_terms_project_locale_source",
            "project_id",
            "locale_code",
            "source_term",
            unique=True,
        ),
    )

    id: str = Field(primary_key=True)
    project_id: str
    locale_code: str
    source_term: str
    target_term: str
    rule: str = Field(default="must_use")
    match_type: str = Field(default="whole_token")
    case_sensitive: int = Field(default=1)
    allow_compounds: int = Field(default=0)
    compound_strategy: str = Field(default="hyphenate")
    negative_patterns_json: str = Field(default="[]")
    notes: str | None = None
    created_at: str
    updated_at: str


class QAFlag(SQLModel, table=True):
    __tablename__ = "qa_flags"
    __table_args__ = (Index("idx_qa_flags_segment_target", "segment_id", "target_locale"),)

    id: str = Field(primary_key=True)
    segment_id: str
    target_locale: str
    type: str
    severity: str
    message: str
    span_json: str = Field(default="{}")
    created_at: str
    resolved_at: str | None = None
    resolved_by: str | None = None
    resolution: str | None = None


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (Index("idx_jobs_project_created_at", "project_id", "created_at"),)

    id: str = Field(primary_key=True)
    project_id: str
    asset_id: str | None = None
    job_type: str
    targets_json: str = Field(default="[]")
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    summary: str | None = None
    decision_trace_json: str = Field(default="{}")
