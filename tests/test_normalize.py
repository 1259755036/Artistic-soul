from app import normalizer, validator
from app.config_loader import config_loader


def test_normalizer_float():
    raw = {"qty_mt": "2,500", "price": "545"}
    normalized = normalizer.normalize_record(raw)
    assert normalized["qty_mt"] == 2500.0
    assert normalized["price"] == 545.0


def test_normalizer_date():
    raw = {"date": "12 Oct 2025"}
    normalized = normalizer.normalize_record(raw)
    assert normalized["date"] == "2025-10-12"


def test_validator_required_fields():
    record = {field.name: None for field in config_loader.get_field_definitions()}
    is_valid, reasons = validator.validate_record(record)
    assert not is_valid
    assert any("date is required" in reason for reason in reasons)


def test_validator_enum_rejection():
    record = {field.name: None for field in config_loader.get_field_definitions()}
    record["product"] = "INVALID"
    is_valid, reasons = validator.validate_record(record)
    assert not is_valid
    assert any("product must be one of" in reason for reason in reasons)
