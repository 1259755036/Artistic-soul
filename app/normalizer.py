from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from dateutil import parser as date_parser
from dateutil import tz

from .config_loader import config_loader

SG_TZ = tz.gettz("Asia/Singapore")


def _normalize_date(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = date_parser.parse(str(value))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SG_TZ)
    dt = dt.astimezone(SG_TZ)
    return dt.date().isoformat()


def _normalize_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    multiplier = 1.0
    if text.lower().endswith("k"):
        multiplier = 1000.0
        text = text[:-1]
    if text.lower().endswith("m"):
        multiplier = 1_000_000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def _normalize_enum(value: Any, allowed: Optional[List[str]]) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if allowed:
        for option in allowed:
            if text.lower() == option.lower():
                return option
    return text.upper()


def _apply_synonym(field_name: str, value: Optional[str]) -> Optional[str]:
    if value in (None, ""):
        return None
    synonyms = config_loader.get_synonyms().get(field_name, {})
    mapped = synonyms.get(str(value).lower())
    if mapped:
        return mapped
    return str(value).strip()


def normalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for field_def in config_loader.get_field_definitions():
        raw_value = record.get(field_def.name)
        value: Any
        if field_def.type == "date":
            value = _normalize_date(raw_value)
        elif field_def.type == "number":
            value = _normalize_number(raw_value)
        elif field_def.type == "enum":
            value = _normalize_enum(raw_value, field_def.allowed)
        else:
            value = raw_value.strip() if isinstance(raw_value, str) else raw_value

        if isinstance(value, str):
            value = value.strip() or None

        if field_def.synonyms_from and isinstance(value, str):
            value = _apply_synonym(field_def.name, value)

        if value is None and field_def.default is not None:
            value = field_def.default

        normalized[field_def.name] = value

    return normalized
