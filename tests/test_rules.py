from app import rules_engine


def test_multi_product_split_and_price_routing():
    text = "MOUNT LOGAN / 21-25 NOV / HSFO 800-1000 / LSMGO 50-100 / AGENT SEAWAVE / DONE 377/729+1.5K if below 100mts - EPS"
    records = rules_engine.extract_records(text)
    assert len(records) == 2

    hsfo = next(record for record in records if record["product"] == "HSFO380")
    lsmgo = next(record for record in records if record["product"] == "LSMGO")

    assert hsfo["qty_min_mt"] == 800.0
    assert hsfo["qty_max_mt"] == 1000.0
    assert hsfo["price_usd_mt"] == 377.0
    assert hsfo["barging_fee_usd"] == 1500.0
    assert hsfo["buyer"] == "EPS"
    assert hsfo["agent"] == "SEAWAVE"

    assert lsmgo["qty_min_mt"] == 50.0
    assert lsmgo["qty_max_mt"] == 100.0
    assert lsmgo["price_usd_mt"] == 729.0
    assert lsmgo["barging_fee_usd"] == 1500.0


def test_parse_qty_range_variants():
    segment = "CISA - Stelios Y - 2250-2450mt HSFO - eta 18 - 19 Nov (pre norm)"
    result = rules_engine.parse_qty(segment, ["HSFO380"])
    assert result["per_product"]["HSFO380"]["qty_min_mt"] == 2250.0
    assert result["per_product"]["HSFO380"]["qty_max_mt"] == 2450.0

    segment2 = "HSFO 800–1000 MT"
    result2 = rules_engine.parse_qty(segment2, ["HSFO380"])
    assert result2["per_product"]["HSFO380"]["qty_min_mt"] == 800.0
    assert result2["per_product"]["HSFO380"]["qty_max_mt"] == 1000.0

    segment3 = "LSMGO 50/100"
    result3 = rules_engine.parse_qty(segment3, ["LSMGO"])
    assert result3["per_product"]["LSMGO"]["qty_min_mt"] == 50.0
    assert result3["per_product"]["LSMGO"]["qty_max_mt"] == 100.0


def test_parse_dates():
    year = 2025
    eta_segment = "eta 18 - 19 Nov"
    eta = rules_engine.parse_dates(eta_segment, year)
    assert eta["eta_start"] == "2025-11-18"
    assert eta["eta_end"] == "2025-11-19"

    laycan_segment = "laycan 2025/11/11-2025/11/17"
    laycan = rules_engine.parse_dates(laycan_segment, year)
    assert laycan["laycan_start"] == "2025-11-11"
    assert laycan["laycan_end"] == "2025-11-17"

    single_segment = "ETA 10TH NOV"
    single = rules_engine.parse_dates(single_segment, year)
    assert single["eta_start"] == "2025-11-10"
    assert single["eta_end"] == "2025-11-10"

    november_segment = "11-12 NOV SGP"
    november = rules_engine.parse_dates(november_segment, year)
    assert november["eta_start"] == "2025-11-11"
    assert november["eta_end"] == "2025-11-12"

    text_segment = "NOVEMBER 22,2025"
    text_date = rules_engine.parse_dates(text_segment, year)
    assert text_date["eta_start"] == "2025-11-22"
    assert text_date["eta_end"] == "2025-11-22"


def test_parse_parties_and_status():
    segment = "- PIL AGENT SEAWAVE CISA - Stelios Y SOLD"
    result = rules_engine.parse_parties_and_status(segment)
    assert result["buyer"] == "PIL"
    assert result["agent"] == "SEAWAVE"
    assert result["broker"] == "CISA"
    assert result["status"] == "SOLD"

    supplier_segment = "sunrise 377 DONE"
    supplier_result = rules_engine.parse_parties_and_status(supplier_segment)
    assert supplier_result["supplier"] == "SUNRISE"
    assert supplier_result["status"] == "DONE"
