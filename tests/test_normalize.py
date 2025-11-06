from app import normalizer, validator
from app.config_loader import config_loader


def _base_record():
    return {field.name: None for field in config_loader.get_field_definitions()}


def test_normalizer_handles_thousand_suffix():
    raw = _base_record()
    raw.update({"product": "HSFO380", "price_usd_mt": "1.5K", "currency": "usd", "port": "sin"})
    normalized = normalizer.normalize_record(raw)
    assert normalized["price_usd_mt"] == 1500.0
    assert normalized["currency"] == "USD"
    assert normalized["port"] == "Singapore"


def test_validator_rejects_non_positive_quantity():
    record = _base_record()
    record.update({"product": "HSFO380", "qty_mt": -5})
    normalized = normalizer.normalize_record(record)
    is_valid, reasons = validator.validate_record(normalized)
    assert not is_valid
    assert any("qty_mt" in reason for reason in reasons)


def test_validator_required_product():
    record = _base_record()
    is_valid, reasons = validator.validate_record(record)
    assert not is_valid
    assert any("product" in reason for reason in reasons)
