from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from tt_core.review.review_service import list_approved_for_asset

_SAFE_CHARS = re.compile(r"[^a-zA-Z0-9_-]+")


@dataclass(slots=True)
class ExportPatchResult:
    path: Path
    row_count: int
    file_format: str


def _utc_timestamp_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _safe_fragment(value: str) -> str:
    cleaned = _SAFE_CHARS.sub("_", value.strip())
    return cleaned.strip("_") or "patch"


def export_patch_file(
    *,
    db_path: Path,
    project_slug: str,
    project_path: Path,
    asset_id: str,
    target_locale: str,
    file_format: str,
    filename_prefix: str = "patch",
) -> ExportPatchResult:
    normalized_format = file_format.strip().lower()
    if normalized_format not in {"xlsx", "csv"}:
        raise ValueError("file_format must be 'xlsx' or 'csv'")

    approved_rows = list_approved_for_asset(
        db_path=db_path,
        asset_id=asset_id,
        target_locale=target_locale,
    )
    if not approved_rows:
        raise ValueError("No approved translations found for this asset and locale")

    include_cn = any(item.cn_text is not None for item in approved_rows)
    records: list[dict[str, object | None]] = []
    for item in approved_rows:
        row_payload: dict[str, object | None] = {
            "key": item.key,
            "source_text": item.source_text,
            "approved_target_text": item.approved_target_text,
            "row_index": item.row_index,
            "sheet_name": item.sheet_name,
        }
        if include_cn:
            row_payload["cn_text"] = item.cn_text
        records.append(row_payload)

    dataframe = pd.DataFrame.from_records(records)

    exports_dir = Path(project_path) / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    filename = (
        f"{_safe_fragment(filename_prefix)}_"
        f"{_safe_fragment(project_slug)}_"
        f"{asset_id[:8]}_"
        f"{_safe_fragment(target_locale)}_"
        f"{_utc_timestamp_token()}."
        f"{normalized_format}"
    )
    output_path = exports_dir / filename

    if normalized_format == "csv":
        dataframe.to_csv(output_path, index=False)
    else:
        dataframe.to_excel(output_path, index=False, engine="openpyxl")

    return ExportPatchResult(
        path=output_path,
        row_count=len(records),
        file_format=normalized_format,
    )

