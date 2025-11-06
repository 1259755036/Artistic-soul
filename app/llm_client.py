import json
import os
from pathlib import Path
from typing import Any, Dict, List

import httpx

from .config_loader import config_loader
from .storage import log_event

PROMPT_TEMPLATE = (Path(__file__).resolve().parent / "prompts" / "extraction_prompt.txt").read_text()


def _build_prompt(text: str) -> str:
    schema_json = config_loader.get_schema_json()
    return PROMPT_TEMPLATE.replace("{{json_schema}}", schema_json).replace("{{text}}", text)


def extract_with_llm(text: str) -> List[Dict[str, Any]]:
    api_key = os.getenv("DS_API_KEY")
    api_base = os.getenv("DS_API_BASE", "https://api.deepseek.com/v1")
    model = os.getenv("DS_MODEL", "deepseek-chat")

    if not api_key:
        return []

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an information extractor that outputs ONLY valid JSON matching the provided schema.",
            },
            {"role": "user", "content": _build_prompt(text)},
        ],
        "temperature": 0,
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        response = httpx.post(f"{api_base.rstrip('/')}/chat/completions", headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return parsed
    except Exception as exc:  # noqa: BLE001
        log_event(f"LLM extraction failed: {exc}")
    return []
