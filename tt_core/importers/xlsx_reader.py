from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

SUPPORTED_FILE_TYPES = {"xlsx", "csv"}


def infer_file_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsx":
        return "xlsx"
    if suffix == ".csv":
        return "csv"
    raise ValueError("Unsupported file type. Use .xlsx or .csv")


def list_xlsx_sheets(*, file_bytes: bytes | None = None, file_path: Path | None = None) -> list[str]:
    source = _resolve_source(file_bytes=file_bytes, file_path=file_path)
    with pd.ExcelFile(source, engine="openpyxl") as workbook:
        return list(workbook.sheet_names)


def read_tabular_data(
    *,
    file_type: str,
    file_bytes: bytes | None = None,
    file_path: Path | None = None,
    sheet_name: str | None = None,
) -> pd.DataFrame:
    normalized_type = file_type.lower()
    if normalized_type not in SUPPORTED_FILE_TYPES:
        raise ValueError(f"Unsupported file_type: {file_type}")

    source = _resolve_source(file_bytes=file_bytes, file_path=file_path)

    if normalized_type == "xlsx":
        selected_sheet = sheet_name if sheet_name is not None else 0
        dataframe = pd.read_excel(
            source,
            sheet_name=selected_sheet,
            dtype=object,
            engine="openpyxl",
        )
    else:
        dataframe = pd.read_csv(source, dtype=object)

    dataframe = dataframe.copy()
    dataframe.columns = _normalize_columns(list(dataframe.columns))
    return dataframe


def preview_dataframe(dataframe: pd.DataFrame, limit: int = 20) -> pd.DataFrame:
    return dataframe.head(limit).copy()


def _resolve_source(*, file_bytes: bytes | None, file_path: Path | None) -> io.BytesIO | Path:
    if file_bytes is not None:
        return io.BytesIO(file_bytes)

    if file_path is None:
        raise ValueError("Either file_bytes or file_path is required")

    return Path(file_path).expanduser()


def _normalize_columns(columns: list[object]) -> list[str]:
    normalized: list[str] = []
    for index, column in enumerate(columns):
        if column is None:
            normalized.append(f"column_{index + 1}")
            continue

        try:
            if pd.isna(column):
                normalized.append(f"column_{index + 1}")
                continue
        except TypeError:
            pass

        column_name = str(column).strip()
        normalized.append(column_name or f"column_{index + 1}")

    return normalized
