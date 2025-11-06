from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List

import pandas as pd
from openpyxl.styles import Font

from .config_loader import config_loader


def _numeric_columns() -> List[str]:
    return [field.name for field in config_loader.get_field_definitions() if field.type == "number"]


def export_records(records: List[Dict[str, Any]]) -> BytesIO:
    if not records:
        raise ValueError("No records to export")

    field_order = [field.name for field in config_loader.get_field_definitions()]
    ordered_records = []
    for record in records:
        ordered_records.append({field: record.get(field) for field in field_order})

    df = pd.DataFrame(ordered_records, columns=field_order)
    numeric_cols = [col for col in _numeric_columns() if col in df.columns]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Records")
        sheet = writer.sheets["Records"]
        sheet.freeze_panes = "A2"
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for column_cells in sheet.columns:
            max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
            adjusted = max(12, max_length + 2)
            sheet.column_dimensions[column_cells[0].column_letter].width = adjusted
        number_format_columns = {col: idx + 1 for idx, col in enumerate(field_order) if col in numeric_cols}
        for col_name, excel_idx in number_format_columns.items():
            for cell in sheet.iter_rows(min_row=2, min_col=excel_idx, max_col=excel_idx):
                cell[0].number_format = "#,##0.00"

    output.seek(0)
    return output


def default_filename() -> str:
    return f"export_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
