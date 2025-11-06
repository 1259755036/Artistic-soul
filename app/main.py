from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from . import normalizer, rules_engine, validator
from .config_loader import config_loader
from .excel_exporter import default_filename, export_records
from .llm_client import extract_with_llm
from .schemas import (
    ConfigReloadResponse,
    ParseRequest,
    ParseResponse,
    RecordListResponse,
    RecordStatus,
    ReviewUpdate,
)
from .storage import (
    compute_hash,
    fetch_record,
    find_by_hash,
    init_db,
    list_records,
    log_event,
    save_record,
    update_record,
)

app = FastAPI(title="Text to Excel Extractor")
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/review", response_class=HTMLResponse)
async def review_page(request: Request) -> HTMLResponse:
    records = list_records()
    return templates.TemplateResponse("review.html", {"request": request, "records": records})


def _load_texts_from_request(data: Dict[str, Any]) -> List[str]:
    texts: List[str] = []
    if data.get("text"):
        texts.append(str(data["text"]))
    if data.get("texts"):
        texts.extend([str(item) for item in data["texts"] if item])
    return texts


def _merge_records(base: Dict[str, Any], llm_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = {field.name: None for field in config_loader.get_field_definitions()}
    merged.update(base)
    if llm_data:
        for key, value in llm_data.items():
            if merged.get(key) in (None, "") and value not in (None, ""):
                merged[key] = value
    for field in config_loader.get_field_definitions():
        if merged.get(field.name) is None and field.default is not None:
            merged[field.name] = field.default
    return merged


def _process_single_record(raw_text: str, record_data: Dict[str, Any], llm_data: Optional[Dict[str, Any]]) -> ParseResponse:
    merged = _merge_records(record_data, llm_data)

    normalized = normalizer.normalize_record(merged)

    is_valid, reasons = validator.validate_record(normalized)

    model = config_loader.get_model()
    try:
        validated = model(**{**normalized})
        normalized = validated.dict()
    except ValidationError as exc:
        is_valid = False
        try:
            errors = json.loads(exc.json())
            reasons.extend(err["msg"] for err in errors)
        except Exception:  # noqa: BLE001
            reasons.append(str(exc))

    status = RecordStatus.VALID if is_valid else RecordStatus.NEEDS_REVIEW

    record_hash = compute_hash(normalized)
    duplicate = find_by_hash(record_hash)
    if duplicate:
        reasons.append(f"Possible duplicate of record {duplicate['id']}")
        status = RecordStatus.NEEDS_REVIEW

    record_id = save_record(raw_text, normalized, status, reasons)

    return ParseResponse(records=[normalized], status=status, reasons=reasons, record_id=record_id)


def _process_text(raw_text: str, use_llm: bool) -> List[ParseResponse]:
    records = rules_engine.extract_records(raw_text)
    llm_results: List[Dict[str, Any]] = []
    if use_llm:
        llm_results = extract_with_llm(raw_text)

    responses: List[ParseResponse] = []
    for idx, record_data in enumerate(records):
        llm_data = llm_results[idx] if idx < len(llm_results) else None
        responses.append(_process_single_record(raw_text, record_data, llm_data))
    return responses


@app.post("/parse")
async def parse_endpoint(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "")
    use_llm = False
    texts: List[str] = []

    if "application/json" in content_type:
        data = await request.json()
        parse_request = ParseRequest(**data)
        use_llm = parse_request.use_llm
        texts = _load_texts_from_request(data)
    elif "multipart/form-data" in content_type:
        form = await request.form()
        use_llm = form.get("use_llm") in {"true", "on", "1", True}
        text = form.get("text")
        if text:
            texts.append(str(text))
        upload = form.get("file")
        if upload:
            file_bytes = await upload.read()
            texts.append(file_bytes.decode("utf-8", errors="ignore"))
    else:
        raise HTTPException(status_code=400, detail="Unsupported content type")

    if not texts:
        raise HTTPException(status_code=400, detail="No text provided")

    results: List[ParseResponse] = []
    for raw_text in texts:
        results.extend(_process_text(raw_text, use_llm))

    log_event(f"Parsed {len(results)} record(s) use_llm={use_llm}")
    return JSONResponse([result.dict() for result in results])


@app.get("/api/records", response_model=List[RecordListResponse])
async def api_records(status: Optional[RecordStatus] = None) -> List[RecordListResponse]:
    records = list_records(status)
    return [
        RecordListResponse(
            id=record["id"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            raw_text=record["raw_text"],
            parsed=record["parsed"],
            status=record["status"],
            reasons=record["reasons"],
        )
        for record in records
    ]


@app.post("/review/{record_id}", response_model=RecordListResponse)
async def update_review(record_id: int, payload: ReviewUpdate) -> RecordListResponse:
    existing = fetch_record(record_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Record not found")

    status = payload.status
    is_valid, reasons = validator.validate_record(payload.parsed)
    if not is_valid:
        status = RecordStatus.NEEDS_REVIEW

    update_record(record_id, payload.parsed, status, reasons)
    refreshed = fetch_record(record_id)
    return RecordListResponse(
        id=refreshed["id"],
        created_at=refreshed["created_at"],
        updated_at=refreshed["updated_at"],
        raw_text=refreshed["raw_text"],
        parsed=refreshed["parsed"],
        status=refreshed["status"],
        reasons=refreshed["reasons"],
    )


@app.get("/export.xlsx")
async def export_endpoint(status: Optional[RecordStatus] = None):
    records = list_records(status)
    payload = [record["parsed"] for record in records if status or record["status"] == RecordStatus.APPROVED]
    if not payload:
        raise HTTPException(status_code=400, detail="No records available for export")
    buffer = export_records(payload)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={default_filename()}"},
    )


@app.post("/api/reload-config", response_model=ConfigReloadResponse)
async def reload_config() -> ConfigReloadResponse:
    reloaded = config_loader.reload_if_needed()
    return ConfigReloadResponse(reloaded=reloaded)
