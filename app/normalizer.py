from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .config_loader import config_loader


DATE_FORMATS = [
    "%Y-%m-%d",
    "%d %b %Y",
    "%d %b %y",
    "%d %B %Y",
    "%d %B %y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d/%b/%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
]


def _normalize_date(value: Any, instructions: List[str]) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    text = text.replace("/", " ").replace("-", " ").replace(",", " ")
    text = " ".join(text.split())
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.date().isoformat()
        except ValueError:
            continue
    # fallback for formats like 12 Oct 2025 (with month abbreviation) already handled
    return None


def _normalize_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = str(value).replace(",", "").strip()
        return float(cleaned)
    except ValueError:
        return None


def normalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    field_defs = config_loader.get_field_definitions()
    normalized: Dict[str, Any] = {}

    for field_def in field_defs:
        value = record.get(field_def.name)
        instructions = field_def.normalize or []

        if field_def.type == "date" and any(inst.startswith("to_iso_date") for inst in instructions):
            normalized[field_def.name] = _normalize_date(value, instructions)
            continue

        if field_def.type == "number" and any(inst.startswith("to_float") for inst in instructions):
            normalized[field_def.name] = _normalize_float(value)
            continue

        if field_def.name == "currency" and isinstance(value, str):
            normalized[field_def.name] = value.upper()
            continue

        normalized[field_def.name] = value

    return normalized
