from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from pydantic import ValidationError

from .config_loader import config_loader
from .storage import log_event

PROMPT_TEMPLATE = (Path(__file__).resolve().parent / "prompts" / "extraction_prompt.txt").read_text()
MAX_ATTEMPTS = 3
_BACKOFF_BASE = 2


def _build_prompt(text: str, schema: Dict[str, Any]) -> str:
    schema_json = json.dumps(schema, sort_keys=True)
    return PROMPT_TEMPLATE.replace("{{json_schema}}", schema_json).replace("{{text}}", text)


def _clean_llm_record(data: Dict[str, Any]) -> Dict[str, Any]:
    allowed_fields = [field.name for field in config_loader.get_field_definitions()]
    cleaned = {field: None for field in allowed_fields}
    for key, value in data.items():
        if key in cleaned:
            cleaned[key] = value
    return cleaned


def extract_with_llm(text: str, schema: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    api_key = os.getenv("DS_API_KEY")
    if not api_key:
        return []

    api_base = os.getenv("DS_API_BASE", "https://api.deepseek.com/v1").rstrip("/")
    model = os.getenv("DS_MODEL", "deepseek-chat")
    compat = os.getenv("DS_COMPAT", "openai").lower()

    schema_dict = schema or json.loads(config_loader.get_schema_json())
    prompt = _build_prompt(text, schema_dict)

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an information extractor that outputs ONLY valid JSON matching the provided schema.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "top_p": 0,
        "max_tokens": 512,
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    endpoint = f"{api_base}/chat/completions" if compat == "openai" else f"{api_base}/chat/completions"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                parsed = [parsed]
            if not isinstance(parsed, list):
                return []

            model_cls = config_loader.get_model()
            cleaned_results: List[Dict[str, Any]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                cleaned = _clean_llm_record(item)
                try:
                    validated = model_cls(**{k: v for k, v in cleaned.items() if v is not None})
                    cleaned_results.append({**cleaned, **validated.dict()})
                except ValidationError as exc:
                    log_event(f"LLM validation failed: {exc}")
            return cleaned_results
        except httpx.HTTPError as exc:
            log_event(f"LLM request failed (attempt {attempt}): {exc}")
        except (KeyError, json.JSONDecodeError) as exc:
            log_event(f"LLM response parse error: {exc}")
            return []

        time.sleep((_BACKOFF_BASE ** attempt))

    return []


__all__ = ["extract_with_llm"]
