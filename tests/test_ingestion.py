import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import init_db

init_db()
client = TestClient(app)


def test_parse_csv_ingestion(tmp_path):
    csv_content = "text\n\"KOTA VALPARAISO / 21 NOV / HSFO 600 DONE 376.50 - PIL\""
    files = {"file": ("sample.csv", csv_content, "text/csv")}
    response = client.post("/parse", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data
    record = data[0]["records"][0]
    assert record["product"] == "HSFO380"
    assert record["buyer"] == "PIL"
    assert record["status"] in {"DONE", "UNKNOWN"}


def test_parse_docx_ingestion():
    pytest.importorskip("docx", reason="python-docx not installed")
    from docx import Document  # type: ignore[import]

    document = Document()
    document.add_paragraph("SV ADELAIDE / 11-12 NOV SGP / 50MT LSMGO SOLD OLDENDORFF USD 730+ USD 1500 barging")
    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    files = {
        "file": (
            "sample.docx",
            buffer.read(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    response = client.post("/parse", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data
    record = data[0]["records"][0]
    assert record["product"] == "LSMGO"
    assert record["price_usd_mt"] == 730.0
    assert record["barging_fee_usd"] == 1500.0
