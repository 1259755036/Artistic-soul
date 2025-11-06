from typing import Any, Dict, List, Tuple

from .config_loader import config_loader


def validate_record(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    field_defs = config_loader.get_field_definitions()
    reasons: List[str] = []

    for field_def in field_defs:
        value = record.get(field_def.name)
        if field_def.required and (value is None or value == ""):
            reasons.append(f"{field_def.name} is required")
            continue

        if field_def.type == "enum" and value is not None:
            if value not in (field_def.allowed or []):
                reasons.append(f"{field_def.name} must be one of {field_def.allowed}")

        if field_def.type == "number" and value is not None:
            try:
                float(value)
            except (TypeError, ValueError):
                reasons.append(f"{field_def.name} must be numeric")

    return (len(reasons) == 0, reasons)
