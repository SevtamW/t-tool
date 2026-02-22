from __future__ import annotations

import hashlib
from collections.abc import Sequence


def build_signature_input(
    file_type: str,
    sheet_name: str | None,
    column_names: Sequence[str],
) -> str:
    normalized_file_type = file_type.upper()
    normalized_sheet_name = sheet_name or ""
    normalized_columns = [str(column) for column in column_names]
    return (
        f"{normalized_file_type}|{normalized_sheet_name}|"
        f"colcount={len(normalized_columns)}|"
        f"cols={','.join(normalized_columns)}"
    )


def compute_schema_signature(
    file_type: str,
    sheet_name: str | None,
    column_names: Sequence[str],
) -> str:
    signature_input = build_signature_input(file_type, sheet_name, column_names)
    return hashlib.sha256(signature_input.encode("utf-8")).hexdigest()
