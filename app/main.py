from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Request, UploadFile
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

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

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
    fields = config_loader.get_field_definitions()
    return templates.TemplateResponse("review.html", {"request": request, "records": records, "fields": fields})


def _ensure_limit(total_bytes: int) -> None:
    if total_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Payload exceeds 5MB limit")


def _load_texts_from_json(data: Dict[str, Any]) -> List[str]:
    texts: List[str] = []
    if data.get("text"):
        texts.append(str(data["text"]))
    if data.get("texts"):
        texts.extend([str(item) for item in data["texts"] if item])
    total_bytes = sum(len(text.encode("utf-8")) for text in texts)
    _ensure_limit(total_bytes)
    return texts


async def _decode_upload(upload: UploadFile) -> Tuple[List[str], Optional[str]]:
    file_bytes = await upload.read()
    _ensure_limit(len(file_bytes))
    filename = upload.filename or ""
    suffix = Path(filename).suffix.lower()
    text_source = None

    if suffix == ".csv":
        text_source = "csv"
        decoded = file_bytes.decode("utf-8", errors="ignore")
        reader = csv.reader(io.StringIO(decoded))
        rows = []
        for row in reader:
            if len(row) == 1 and row[0].strip().lower() == "text":
                continue
            if not any(cell.strip() for cell in row):
                continue
            rows.append(" | ".join(filter(None, row)).strip())
        return rows, text_source

    if suffix == ".docx":
        try:
            from docx import Document  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise HTTPException(status_code=400, detail="DOCX support requires python-docx to be installed") from exc
        text_source = "manual"
        document = Document(io.BytesIO(file_bytes))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        return paragraphs, text_source

    decoded_text = file_bytes.decode("utf-8", errors="ignore")
    text_source = "whatsapp"
    return [decoded_text], text_source


def _merge_records(base: Dict[str, Any], llm_data: Optional[Dict[str, Any]], source_override: Optional[str]) -> Dict[str, Any]:
    merged = {field.name: None for field in config_loader.get_field_definitions()}
    base_clean = {k: v for k, v in base.items() if not k.startswith("__")}
    merged.update(base_clean)
    if source_override:
        merged["source"] = source_override
    if llm_data:
        for key, value in llm_data.items():
            if key in merged and merged.get(key) in (None, "") and value not in (None, ""):
                merged[key] = value
    for field in config_loader.get_field_definitions():
        if merged.get(field.name) is None and field.default is not None:
            merged[field.name] = field.default
    return merged


def _match_llm_record(record: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    product = record.get("product")
    if product:
        for idx, candidate in enumerate(candidates):
            if candidate.get("product") == product:
                return candidates.pop(idx)
    return candidates.pop(0)


def _process_single_record(
    raw_text: str,
    record_data: Dict[str, Any],
    llm_candidates: List[Dict[str, Any]],
    source_override: Optional[str],
    strict: bool,
) -> ParseResponse:
    llm_data = _match_llm_record(record_data, llm_candidates)
    merged = _merge_records(record_data, llm_data, source_override)
    normalized = normalizer.normalize_record(merged)

    is_valid, reasons = validator.validate_record(normalized)

    model = config_loader.get_model()
    try:
        model(**{k: v for k, v in normalized.items() if v is not None})
    except ValidationError as exc:
        is_valid = False
        try:
            errors = json.loads(exc.json())
            reasons.extend(err["msg"] for err in errors)
        except Exception:  # noqa: BLE001
            reasons.append(str(exc))

    if strict and not is_valid:
        raise HTTPException(status_code=422, detail={"record": normalized, "reasons": reasons})

    status = RecordStatus.VALID if is_valid else RecordStatus.NEEDS_REVIEW

    record_hash = compute_hash(normalized)
    duplicate = find_by_hash(record_hash)
    if duplicate:
        reasons.append(f"Possible duplicate of record {duplicate['id']}")
        status = RecordStatus.NEEDS_REVIEW

    record_id = save_record(raw_text, normalized, status, reasons)

    return ParseResponse(records=[normalized], status=status, reasons=reasons, record_id=record_id)


def _collect_llm_enrichment(segment: str, use_llm: bool) -> List[Dict[str, Any]]:
    if not use_llm:
        return []
    return extract_with_llm(segment)


def _process_text(raw_text: str, use_llm: bool, strict: bool, source_override: Optional[str]) -> List[ParseResponse]:
    rule_records = rules_engine.extract_records(raw_text)
    responses: List[ParseResponse] = []

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in rule_records:
        segment = record.get("__segment__", raw_text)
        grouped.setdefault(segment, []).append(record)

    for segment, records in grouped.items():
        llm_candidates = list(_collect_llm_enrichment(segment, use_llm))
        for record in records:
            responses.append(_process_single_record(raw_text, record, llm_candidates, source_override, strict))

    return responses


@app.post("/parse")
async def parse_endpoint(request: Request, use_llm: Optional[bool] = None, strict: bool = False) -> JSONResponse:
    content_type = request.headers.get("content-type", "")
    texts: List[str] = []
    sources: List[Optional[str]] = []
    use_llm_flag = use_llm if use_llm is not None else False

    if "application/json" in content_type:
        data = await request.json()
        parse_request = ParseRequest(**data)
        use_llm_flag = parse_request.use_llm if use_llm is None else use_llm_flag
        texts = _load_texts_from_json(data)
        sources = [None] * len(texts)
    elif "multipart/form-data" in content_type:
        form = await request.form()
        if use_llm is None:
            use_llm_flag = form.get("use_llm") in {"true", "on", "1", True}
        text = form.get("text")
        if text:
            text_str = str(text)
            _ensure_limit(len(text_str.encode("utf-8")))
            texts.append(text_str)
            sources.append(None)
        upload = form.get("file")
        if upload:
            file_texts, source_override = await _decode_upload(upload)
            texts.extend(file_texts)
            sources.extend([source_override] * len(file_texts))
    else:
        raise HTTPException(status_code=400, detail="Unsupported content type")

    if not texts:
        raise HTTPException(status_code=400, detail="No text provided")

    results: List[ParseResponse] = []
    for raw_text, source_override in zip(texts, sources or [None] * len(texts)):
        results.extend(_process_text(raw_text, use_llm_flag, strict, source_override))

    log_event(f"Parsed {len(results)} record(s) use_llm={use_llm_flag} strict={strict}")
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
async def export_endpoint() -> StreamingResponse:
    records = list_records(RecordStatus.APPROVED)
    payload = [record["parsed"] for record in records if record["status"] == RecordStatus.APPROVED]
    if not payload:
        raise HTTPException(status_code=400, detail="No approved records available for export")
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
