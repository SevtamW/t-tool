from __future__ import annotations

import hashlib
import json
import numbers
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from tt_core.db.schema import initialize_database
from tt_core.importers.signature import compute_schema_signature


@dataclass(slots=True, init=False)
class ColumnMapping:
    source_new: str
    source_old: str | None = None
    target: str | None = None
    target_locale: str | None = None
    cn: str | None = None
    key: str | None = None
    char_limit: str | None = None
    context: list[str] = field(default_factory=list)
    mode: str = "lp"

    def __init__(
        self,
        *,
        source_new: str | None = None,
        source: str | None = None,
        source_old: str | None = None,
        target: str | None = None,
        target_locale: str | None = None,
        cn: str | None = None,
        key: str | None = None,
        char_limit: str | None = None,
        context: list[str] | None = None,
        mode: str = "lp",
    ) -> None:
        resolved_source = source_new if source_new is not None else source
        self.source_new = resolved_source or ""
        self.source_old = source_old
        self.target = target
        self.target_locale = target_locale
        self.cn = cn
        self.key = key
        self.char_limit = char_limit
        self.context = list(context or [])
        self.mode = mode

    @property
    def source(self) -> str:
        return self.source_new

    @classmethod
    def from_mapping_payload(cls, payload: dict[str, object]) -> ColumnMapping:
        columns = payload.get("columns")
        column_values = columns if isinstance(columns, dict) else {}
        context_value = column_values.get("context")
        if isinstance(context_value, list):
            context = [str(item) for item in context_value]
        else:
            context = []

        return cls(
            source_new=_string_or_none(column_values.get("source_new"))
            or _string_or_none(column_values.get("source")),
            source_old=_string_or_none(column_values.get("source_old")),
            target=_string_or_none(column_values.get("target")),
            target_locale=_string_or_none(column_values.get("target_locale")),
            cn=_string_or_none(column_values.get("cn")),
            key=_string_or_none(column_values.get("key")),
            char_limit=_string_or_none(column_values.get("char_limit")),
            context=context,
            mode=_string_or_none(payload.get("mode")) or "lp",
        )


@dataclass(slots=True)
class ImportSummary:
    asset_id: str
    schema_profile_id: str
    signature: str
    imported_rows: int
    skipped_rows: int
    mapped_columns: dict[str, object]


def import_asset(
    *,
    db_path: Path,
    project_id: str,
    source_locale: str,
    dataframe: pd.DataFrame,
    file_type: str,
    original_name: str,
    column_mapping: ColumnMapping,
    sheet_name: str | None = None,
    file_bytes: bytes | None = None,
    storage_path: str | None = None,
    size_bytes: int | None = None,
    content_hash: str | None = None,
) -> ImportSummary:
    normalized_file_type = file_type.lower()
    if normalized_file_type not in {"xlsx", "csv"}:
        raise ValueError(f"Unsupported file_type: {file_type}")

    normalized_sheet_name = (sheet_name or "") if normalized_file_type == "xlsx" else ""

    available_columns = [str(column) for column in dataframe.columns]
    mapping = _normalize_mapping(column_mapping)
    _validate_mapping_columns(mapping, available_columns)

    if content_hash is None and file_bytes is not None:
        content_hash = hashlib.sha256(file_bytes).hexdigest()

    if size_bytes is None:
        if file_bytes is not None:
            size_bytes = len(file_bytes)
        elif storage_path:
            try:
                size_bytes = Path(storage_path).expanduser().stat().st_size
            except OSError:
                size_bytes = None

    mapping_payload = {
        "file_type": normalized_file_type,
        "sheet_name": normalized_sheet_name,
        "columns": {
            "source_new": mapping.source_new,
            "source_old": mapping.source_old,
            "target": mapping.target,
            "target_locale": mapping.target_locale,
            "cn": mapping.cn,
            "key": mapping.key,
            "char_limit": mapping.char_limit,
            "context": mapping.context,
        },
        "mode": mapping.mode,
    }

    signature = compute_schema_signature(
        normalized_file_type,
        normalized_sheet_name,
        available_columns,
    )

    now = _utc_now_iso()
    asset_id = str(uuid4())
    schema_profile_candidate_id = str(uuid4())
    baseline_model_info_json = _to_json({"provider": "import", "kind": "baseline"})

    segment_rows: list[dict[str, object | None]] = []
    baseline_candidate_rows: list[dict[str, object]] = []
    skipped_rows = 0

    for position, (_, row) in enumerate(dataframe.iterrows()):
        source_text = _to_required_text(row.get(mapping.source_new))
        if source_text is None:
            skipped_rows += 1
            continue

        segment_id = str(uuid4())
        source_text_old = (
            _to_optional_text(row.get(mapping.source_old)) if mapping.source_old else None
        )

        segment_rows.append(
            {
                "id": segment_id,
                "asset_id": asset_id,
                "sheet_name": normalized_sheet_name or None,
                "row_index": _compute_row_index(row.name, position),
                "key": _to_optional_text(row.get(mapping.key)) if mapping.key else None,
                "source_locale": source_locale,
                "source_text": source_text,
                "source_text_old": source_text_old,
                "cn_text": _to_optional_text(row.get(mapping.cn)) if mapping.cn else None,
                "context_json": _to_json(_build_context_payload(row, mapping.context)),
                "char_limit": _to_int_or_none(row.get(mapping.char_limit))
                if mapping.char_limit
                else None,
                "placeholders_json": "[]",
            }
        )

        if mapping.target and mapping.target_locale:
            target_text = _to_optional_text(row.get(mapping.target))
            if target_text is not None:
                baseline_candidate_rows.append(
                    {
                        "id": str(uuid4()),
                        "segment_id": segment_id,
                        "target_locale": mapping.target_locale,
                        "candidate_text": target_text,
                        "candidate_type": "existing_target",
                        "score": 1.0,
                        "model_info_json": baseline_model_info_json,
                        "generated_at": now,
                    }
                )

    engine = initialize_database(Path(db_path))

    schema_profile_id = schema_profile_candidate_id
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO assets(
                    id, project_id, asset_type, original_name, source_channel, received_at,
                    content_hash, storage_path, size_bytes
                ) VALUES (
                    :id, :project_id, :asset_type, :original_name, :source_channel, :received_at,
                    :content_hash, :storage_path, :size_bytes
                )
                """
            ),
            {
                "id": asset_id,
                "project_id": project_id,
                "asset_type": normalized_file_type,
                "original_name": original_name,
                "source_channel": "manual",
                "received_at": now,
                "content_hash": content_hash,
                "storage_path": storage_path,
                "size_bytes": size_bytes,
            },
        )

        if segment_rows:
            connection.execute(
                text(
                    """
                    INSERT INTO segments(
                        id, asset_id, sheet_name, row_index, key, source_locale,
                        source_text, source_text_old, cn_text, context_json,
                        char_limit, placeholders_json
                    ) VALUES (
                        :id, :asset_id, :sheet_name, :row_index, :key, :source_locale,
                        :source_text, :source_text_old, :cn_text, :context_json,
                        :char_limit, :placeholders_json
                    )
                    """
                ),
                segment_rows,
            )

        if baseline_candidate_rows:
            insertable_baselines = _filter_unapproved_baseline_candidates(
                connection=connection,
                baseline_candidate_rows=baseline_candidate_rows,
                target_locale=mapping.target_locale,
            )
            if insertable_baselines:
                connection.execute(
                    text(
                        """
                        INSERT INTO translation_candidates(
                            id, segment_id, target_locale, candidate_text,
                            candidate_type, score, model_info_json, generated_at
                        ) VALUES (
                            :id, :segment_id, :target_locale, :candidate_text,
                            :candidate_type, :score, :model_info_json, :generated_at
                        )
                        """
                    ),
                    insertable_baselines,
                )

        connection.execute(
            text(
                """
                INSERT INTO schema_profiles(
                    id, project_id, signature, mapping_json,
                    confidence, confirmed_by_user, created_at, updated_at
                ) VALUES (
                    :id, :project_id, :signature, :mapping_json,
                    :confidence, :confirmed_by_user, :created_at, :updated_at
                )
                ON CONFLICT(project_id, signature) DO UPDATE SET
                    mapping_json = excluded.mapping_json,
                    confidence = excluded.confidence,
                    confirmed_by_user = excluded.confirmed_by_user,
                    updated_at = excluded.updated_at
                """
            ),
            {
                "id": schema_profile_candidate_id,
                "project_id": project_id,
                "signature": signature,
                "mapping_json": _to_json(mapping_payload),
                "confidence": 1.0,
                "confirmed_by_user": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        schema_profile_id_row = connection.execute(
            text(
                """
                SELECT id
                FROM schema_profiles
                WHERE project_id = :project_id AND signature = :signature
                LIMIT 1
                """
            ),
            {"project_id": project_id, "signature": signature},
        ).first()

        if schema_profile_id_row is None:
            raise RuntimeError("Failed to persist schema profile")

        schema_profile_id = str(schema_profile_id_row[0])

    engine.dispose()

    return ImportSummary(
        asset_id=asset_id,
        schema_profile_id=schema_profile_id,
        signature=signature,
        imported_rows=len(segment_rows),
        skipped_rows=skipped_rows,
        mapped_columns={
            "mode": mapping.mode,
            "source_new": mapping.source_new,
            "source_old": mapping.source_old,
            "target": mapping.target,
            "target_locale": mapping.target_locale,
            "cn": mapping.cn,
            "key": mapping.key,
            "char_limit": mapping.char_limit,
            "context": mapping.context,
        },
    )


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _normalize_mapping(mapping: ColumnMapping) -> ColumnMapping:
    context = _unique_preserve(mapping.context)
    return ColumnMapping(
        source_new=_clean_column_name(mapping.source_new) or "",
        source_old=_clean_column_name(mapping.source_old),
        target=_clean_column_name(mapping.target),
        target_locale=_clean_column_name(mapping.target_locale),
        cn=_clean_column_name(mapping.cn),
        key=_clean_column_name(mapping.key),
        char_limit=_clean_column_name(mapping.char_limit),
        context=context,
        mode=_normalize_mode(mapping.mode),
    )


def _clean_column_name(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip()
    return normalized or None


def _validate_mapping_columns(mapping: ColumnMapping, available_columns: list[str]) -> None:
    available = set(available_columns)

    if not mapping.source_new:
        raise ValueError("A source_new column is required")

    if mapping.source_new not in available:
        raise ValueError(f"Mapped source_new column does not exist: {mapping.source_new}")

    if mapping.mode == "change_source_update" and not mapping.source_old:
        raise ValueError("A source_old column is required in change_source_update mode")

    if mapping.source_old and mapping.source_old not in available:
        raise ValueError(f"Mapped source_old column does not exist: {mapping.source_old}")

    if mapping.target_locale and not mapping.target:
        raise ValueError("A target column is required when target_locale is set")

    optional_columns = [mapping.target, mapping.cn, mapping.key, mapping.char_limit]
    for optional in optional_columns:
        if optional and optional not in available:
            raise ValueError(f"Mapped column does not exist: {optional}")

    missing_context = [column for column in mapping.context if column not in available]
    if missing_context:
        raise ValueError(f"Mapped context columns do not exist: {', '.join(missing_context)}")


def _unique_preserve(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)

    return output


def _normalize_mode(value: str | None) -> str:
    normalized = (value or "lp").strip().lower()
    aliases = {
        "lp": "lp",
        "lp (single source)": "lp",
        "change_source_update": "change_source_update",
        "change file (old/new source)": "change_source_update",
    }
    if normalized not in aliases:
        raise ValueError(f"Unsupported import mode: {value}")
    return aliases[normalized]


def _filter_unapproved_baseline_candidates(
    *,
    connection: Connection,
    baseline_candidate_rows: list[dict[str, object]],
    target_locale: str | None,
) -> list[dict[str, object]]:
    if not baseline_candidate_rows or not target_locale:
        return baseline_candidate_rows

    segment_ids = [str(row["segment_id"]) for row in baseline_candidate_rows]
    approved_segment_ids = {
        str(row[0])
        for row in connection.execute(
            text(
                """
                SELECT segment_id
                FROM approved_translations
                WHERE target_locale = :target_locale
                  AND segment_id IN :segment_ids
                """
            ).bindparams(bindparam("segment_ids", expanding=True)),
            {
                "target_locale": target_locale,
                "segment_ids": segment_ids,
            },
        ).all()
    }

    if not approved_segment_ids:
        return baseline_candidate_rows

    return [
        row
        for row in baseline_candidate_rows
        if str(row["segment_id"]) not in approved_segment_ids
    ]


def _build_context_payload(row: pd.Series, context_columns: list[str]) -> dict[str, str | None]:
    context: dict[str, str | None] = {}
    for column in context_columns:
        context[column] = _to_optional_text(row.get(column))
    return context


def _to_required_text(value: object) -> str | None:
    optional_text = _to_optional_text(value)
    if optional_text is None:
        return None
    return optional_text


def _to_optional_text(value: object) -> str | None:
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    text_value = str(value)
    if not text_value.strip():
        return None

    return text_value


def _to_int_or_none(value: object) -> int | None:
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    if isinstance(value, bool):
        return None

    if isinstance(value, numbers.Integral):
        return int(value)

    if isinstance(value, numbers.Real):
        float_value = float(value)
        if float_value.is_integer():
            return int(float_value)
        return None

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return int(normalized)
        except ValueError:
            try:
                float_value = float(normalized)
            except ValueError:
                return None
            if float_value.is_integer():
                return int(float_value)
            return None

    return None


def _compute_row_index(original_index: object, position: int) -> int:
    if isinstance(original_index, numbers.Integral):
        return int(original_index) + 2

    try:
        return int(str(original_index)) + 2
    except (TypeError, ValueError):
        return position + 2


def _to_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
