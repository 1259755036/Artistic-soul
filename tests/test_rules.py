from pathlib import Path

from app import rules_engine

SAMPLES = Path(__file__).with_name("samples.txt").read_text().splitlines()


def test_preprocess_not_empty():
    text = "\u300012 Oct 2025\tTrafigura"
    result = rules_engine.preprocess_text(text)
    assert "Trafigura" in result


def test_extract_records_multiple():
    combined = "\n\n".join(SAMPLES[:2])
    records = rules_engine.extract_records(combined)
    assert len(records) >= 2


def test_extract_product_synonym():
    record = rules_engine.extract_records(SAMPLES[0])[0]
    assert record["product"] == "VLSFO"


def test_quantity_pattern():
    record = rules_engine.extract_records(SAMPLES[1])[0]
    assert record["qty_mt"] in {"2000", "2000", "2000"}
