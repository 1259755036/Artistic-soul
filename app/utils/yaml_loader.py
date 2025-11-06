from __future__ import annotations

import json
from typing import Any, List, Tuple


def safe_load(text: str) -> Any:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ModuleNotFoundError:
        return _fallback_load(text)


def _fallback_load(text: str) -> Any:
    lines = [line.rstrip() for line in text.splitlines()]
    index, result = 0, None
    while index < len(lines):
        if not lines[index].strip() or lines[index].strip().startswith("#"):
            index += 1
            continue
        result, index = _parse_mapping(lines, index, _indent(lines[index]))
        break
    return result


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_mapping(lines: List[str], index: int, indent: int) -> Tuple[Any, int]:
    mapping: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.strip().startswith("#"):
            index += 1
            continue
        current_indent = _indent(line)
        if current_indent < indent:
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            sequence, index = _parse_sequence(lines, index, current_indent)
            return sequence, index
        if ":" not in stripped:
            index += 1
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        index += 1
        if value:
            mapping[key] = _parse_scalar(value)
            continue
        # determine nested structure
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            mapping[key] = None
            break
        next_line = lines[index]
        next_indent = _indent(next_line)
        if next_indent <= current_indent:
            mapping[key] = None
            continue
        if next_line.strip().startswith("- "):
            sequence, index = _parse_sequence(lines, index, next_indent)
            mapping[key] = sequence
        else:
            nested, index = _parse_mapping(lines, index, next_indent)
            mapping[key] = nested
    return mapping, index


def _parse_sequence(lines: List[str], index: int, indent: int) -> Tuple[List[Any], int]:
    sequence: List[Any] = []
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.strip().startswith("#"):
            index += 1
            continue
        current_indent = _indent(line)
        if current_indent < indent:
            break
        stripped = line.strip()
        if not stripped.startswith("- "):
            break
        item_content = stripped[2:].strip()
        index += 1
        if not item_content:
            nested, index = _parse_mapping(lines, index, indent + 2)
            sequence.append(nested)
            continue
        if ":" not in item_content:
            sequence.append(_parse_scalar(item_content))
            continue
        key, value = item_content.split(":", 1)
        key = key.strip()
        value = value.strip()
        item: dict[str, Any] = {}
        if value:
            item[key] = _parse_scalar(value)
        else:
            nested, index = _parse_mapping(lines, index, indent + 2)
            item[key] = nested
        # absorb additional key/value pairs with higher indent
        while index < len(lines):
            lookahead = lines[index]
            if not lookahead.strip() or lookahead.strip().startswith("#"):
                index += 1
                continue
            look_indent = _indent(lookahead)
            if look_indent <= indent:
                break
            if lookahead.strip().startswith("- "):
                break
            if ":" not in lookahead:
                index += 1
                continue
            sub_key, sub_value = lookahead.strip().split(":", 1)
            sub_key = sub_key.strip()
            sub_value = sub_value.strip()
            index += 1
            if sub_value:
                item[sub_key] = _parse_scalar(sub_value)
            else:
                nested, index = _parse_mapping(lines, index, look_indent + 2)
                item[sub_key] = nested
        sequence.append(item)
    return sequence, index


def _parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value.replace("'", '"'))
        except json.JSONDecodeError:
            pass
    if value.startswith("\"") and value.endswith("\""):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value
