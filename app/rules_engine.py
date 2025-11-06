import re
import unicodedata
from typing import Any, Dict, List

from .config_loader import config_loader


def preprocess_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\u3000", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\t+", " ", normalized)
    normalized = re.sub(r"[ ]{2,}", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def split_records(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"\n\s*\n", text)
    if len(parts) > 1:
        return [part.strip() for part in parts if part.strip()]

    bullet_split = re.split(r"(?:^|\n)\s*(?:\d+[\).]|[-*•])\s+", text)
    candidates = [segment.strip() for segment in bullet_split if segment.strip()]
    if len(candidates) > 1:
        return candidates

    if "|" in text:
        return [seg.strip() for seg in text.split("\n") if seg.strip()]

    return [text.strip()]


def _extract_from_patterns(patterns: List[str], text: str) -> Any:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            if match.groups():
                return match.group(1)
            return match.group(0)
    return None


def _extract_from_synonyms(field_name: str, text_lower: str, synonyms_map: Dict[str, Dict[str, str]]) -> Any:
    synonyms = synonyms_map.get(field_name, {})
    for token in sorted(synonyms.keys(), key=len, reverse=True):
        if token and token in text_lower:
            return synonyms[token]
    return None


def extract_with_rules(text: str) -> Dict[str, Any]:
    field_defs = config_loader.get_field_definitions()
    text_lower = text.lower()
    synonyms_map = config_loader.get_synonyms()
    results: Dict[str, Any] = {}

    for field_def in field_defs:
        value = None
        if field_def.patterns:
            value = _extract_from_patterns(field_def.patterns, text)
        if not value and field_def.synonyms_from:
            value = _extract_from_synonyms(field_def.name, text_lower, synonyms_map)
        if not value and field_def.default is not None:
            value = field_def.default
        results[field_def.name] = value
    return results


def extract_records(text: str) -> List[Dict[str, Any]]:
    preprocessed = preprocess_text(text)
    records_text = split_records(preprocessed)
    return [extract_with_rules(record_text) for record_text in records_text]
