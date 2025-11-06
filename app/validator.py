from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as date_parser
from dateutil import tz

from .config_loader import config_loader

SG_TZ = tz.gettz("Asia/Singapore")
_ONE_YEAR = timedelta(days=365)


def _parse_iso_date(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        dt = date_parser.parse(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=SG_TZ)
        return dt
    except (ValueError, TypeError):
        return None


def validate_record(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    field_defs = config_loader.get_field_definitions()
    reasons: List[str] = []

    for field_def in field_defs:
        value = record.get(field_def.name)
        if field_def.required and (value is None or value == ""):
            reasons.append(f"{field_def.name} is required")
            continue

        if field_def.type == "enum" and value is not None:
            allowed = field_def.allowed or []
            if value not in allowed:
                reasons.append(f"{field_def.name} must be one of {allowed}")

        if field_def.type == "number" and value is not None:
            try:
                number_value = float(value)
            except (TypeError, ValueError):
                reasons.append(f"{field_def.name} must be numeric")
                continue
            if field_def.name in {"qty_mt", "qty_min_mt", "qty_max_mt", "price_usd_mt"} and number_value <= 0:
                reasons.append(f"{field_def.name} must be greater than zero")

        if field_def.type == "date" and value:
            parsed = _parse_iso_date(value)
            if not parsed:
                reasons.append(f"{field_def.name} must be a valid date")
            else:
                now = datetime.now(tz=SG_TZ)
                if parsed - now > _ONE_YEAR:
                    reasons.append(f"{field_def.name} is too far in the future")

    return (len(reasons) == 0, reasons)
