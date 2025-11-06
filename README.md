# Text to Excel Extractor

Convert messy, semi-structured trade text into structured tables ready for Excel. The app uses a configurable rule engine with optional LLM assistance (DeepSeek) to parse bunker deal notes and export them as `.xlsx` files.

## Features

- YAML-driven field definitions, patterns, enums, and synonym dictionaries (e.g., `message_ts`, `product`, `qty_min_mt`, `status`)
- FastAPI backend with optional DeepSeek LLM enrichment and strict/lenient validation modes
- SQLite persistence with review workflow and duplicate detection
- Excel export (pandas + openpyxl) with ordered columns, formatting, and frozen headers
- Web UI for paste/upload, review dashboard, and hot-reloadable config
- Comprehensive unit tests for rule extraction and normalization

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env   # fill DS_API_KEY if using LLM
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 to access the UI.

## Configuration

Field definitions live in `config/fields.yaml`. Each field can specify:

- `type`: `string`, `number`, `date`, or `enum`
- `required`: enforce validation
- `patterns`: regex extraction rules
- `normalize`: ordered normalization steps (e.g., `to_iso_date`, `to_float`)
- `allowed`: valid enum values
- `default`: default value when missing
- `synonyms_from`: relative path to a YAML synonyms dictionary

Synonym dictionaries live in `config/entities/`. For example `config/entities/products.yml` maps canonical product names to synonyms such as `"HSFO380"` ← `"HSFO"`, and `config/entities/counterparties.yml` covers buyers, suppliers, brokers, and agents.

Status values are enumerated in config and include `OFFER`, `DONE`, `SOLD`, `ENQUIRY`, `PRENOM`, and `UNKNOWN`.

Reload configuration without restarting via:

```bash
curl -X POST http://127.0.0.1:8000/api/reload-config
```

## DeepSeek LLM (optional)

The rules engine runs first; if `use_llm=true` the system calls the DeepSeek API to fill missing fields. Environment variables (see `.env.example`):

- `DS_API_BASE` (e.g. `https://api.deepseek.com/v1`)
- `DS_API_KEY`
- `DS_MODEL` (default `deepseek-chat`)
- `DS_COMPAT` (default `openai`, for compatible gateways)

Toggle the LLM from the UI or via `POST /parse?use_llm=true`. A `strict=true` query parameter rejects invalid payloads instead of queueing them for review.

LLM payloads are sent with `temperature=0`, `top_p=0`, and `max_tokens=512` to control cost. Only fields still missing after rules are sent for enrichment, and every response is revalidated with Pydantic plus business validation before persisting.

All LLM output is revalidated with Pydantic and business rules before persisting.

## Storage & review

- SQLite DB at `data/records.db`
- `records` table stores raw text, parsed JSON, validation status, reasons, and duplicate hash
- `logs` table keeps simple audit messages
- Review UI (`/review`) lists parsed rows with reasons; approve via `POST /review/{id}`

## Excel export

`GET /export.xlsx` downloads approved records as `export_YYYYMMDD_HHMM.xlsx`.

Export details:

- Column order follows `config/fields.yaml`
- Header row bold, first row frozen
- Numeric values remain numeric; columns auto-sized

## Testing

Run pytest from the repo root:

```bash
pytest
```

CSV, TXT, and (optionally) DOCX uploads are accepted by `/parse`. Install `python-docx` if DOCX ingestion is required.

## Deployment

The project runs entirely locally and targets low-cost hosting such as Render or Railway:

- Use `uvicorn` in production mode (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`)
- Persist the SQLite database on a mounted volume if needed
- Configure environment variables for DeepSeek if using LLM

LLM usage is optional—rules-only extraction keeps costs minimal.
