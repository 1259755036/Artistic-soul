from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as date_parser
from dateutil import tz

from .config_loader import config_loader

SG_TZ = tz.gettz("Asia/Singapore")
_HEADER_PATTERNS = [
    re.compile(
        r"^\[(?P<timestamp>[^\]]+)\]\s*(?P<sender>[^:]+):\s*(?P<body>.*)$",
        re.DOTALL,
    ),
    re.compile(
        r"^(?P<timestamp>\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)\s*-\s*(?P<sender>[^:]+):\s*(?P<body>.*)$",
        re.DOTALL,
    ),
]

_RANGE_SEP = r"(?:-|–|—|to|/)"
_QTY_UNITS = r"(?:mt|tons?|t)"
_RANGE_PATTERN = re.compile(
    rf"(?P<min>\d+(?:\.\d+)?)\s*{_RANGE_SEP}\s*(?P<max>\d+(?:\.\d+)?)(?:\s*{_QTY_UNITS})?",
    re.IGNORECASE,
)
_SINGLE_QTY_PATTERN = re.compile(rf"(?<!\d)(?P<qty>\d+(?:\.\d+)?)(?:\s*{_QTY_UNITS})", re.IGNORECASE)
_BARGING_PATTERN = re.compile(r"barg(?:e|ing)\s*(?:fee)?\s*(?:usd)?\s*(?P<value>[\d.,]+(?:[kK])?)", re.IGNORECASE)
_PREMIUM_PATTERN = re.compile(r"(?:don|premium|prem)\s*[+\-]?\s*(?P<value>[\d.,]+(?:[kK])?)", re.IGNORECASE)
_STATUS_MAP = {
    "sold": "SOLD",
    "done": "DONE",
    "offer": "OFFER",
    "enquiry": "ENQUIRY",
    "pre nom": "PRENOM",
    "pre-nom": "PRENOM",
    "pre norm": "PRENOM",
}
_PRICE_SLASH_PATTERN = re.compile(r"(?P<a>\d+(?:\.\d+)?)\s*/\s*(?P<b>\d+(?:\.\d+)?)")
_PRICE_WITH_KEYWORD = re.compile(r"(?:done|sold|offer|@|usd|us\$)\s*(?P<value>\d+(?:\.\d+)?)", re.IGNORECASE)
_SUPPLIER_PRICE_PATTERN = re.compile(
    r"(?P<supplier>[A-Za-z&'\s]{3,})\s*(?P<value>\d+(?:\.\d+)?)(?!\s*(?:mt|tons?|t))",
    re.IGNORECASE,
)
_DATE_RANGE_YMD = re.compile(
    r"(?P<start>\d{4}[/-]\d{1,2}[/-]\d{1,2})\s*(?:-|–|—|to)\s*(?P<end>\d{4}[/-]\d{1,2}[/-]\d{1,2})",
    re.IGNORECASE,
)
_DATE_RANGE_DAY_MONTH = re.compile(
    rf"(?P<start_day>\d{{1,2}})(?:st|nd|rd|th)?\s*{_RANGE_SEP}\s*(?P<end_day>\d{{1,2}})(?:st|nd|rd|th)?\s*(?P<month>[A-Za-z]{{3,}})",
    re.IGNORECASE,
)
_SINGLE_DATE_MONTH = re.compile(
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s*(?P<month>[A-Za-z]{3,})(?:[\s,]*(?P<year>\d{2,4}))?",
    re.IGNORECASE,
)
_ISO_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MONTH_FIRST_PATTERN = re.compile(
    r"(?P<month>[A-Za-z]{3,})\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:[\s,]*(?P<year>\d{2,4}))?",
    re.IGNORECASE,
)

_ALL_CAPS_LINE = re.compile(r"^[A-Z0-9][A-Z0-9\s\-'/()]+$")
_SEMICOLON_SPLIT = re.compile(r";+")
_SLASH_SPLIT = re.compile(r"\s/\s(?=[A-Z0-9]{3,})")


def _parse_timestamp(text: str) -> Optional[str]:
    try:
        dt = date_parser.parse(text, dayfirst=False, yearfirst=False)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=SG_TZ)
        dt = dt.astimezone(SG_TZ)
        return dt.isoformat()
    except (ValueError, TypeError):
        return None


def strip_chat_header(text: str) -> Tuple[str, Dict[str, Any]]:
    """
    Remove WhatsApp-style chat headers and return body plus metadata.
    """

    if not text:
        return "", {}

    for pattern in _HEADER_PATTERNS:
        match = pattern.match(text.strip())
        if match:
            timestamp = match.group("timestamp")
            sender = match.group("sender").strip()
            body = match.group("body").strip()
            meta: Dict[str, Any] = {}
            parsed_ts = _parse_timestamp(timestamp)
            if parsed_ts:
                meta["message_ts"] = parsed_ts
            if sender:
                meta["chat_sender"] = sender
            return body, meta

    return text.strip(), {}


def _looks_like_new_record(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 5:
        return False
    if _ALL_CAPS_LINE.match(stripped):
        return True
    return False


def split_candidates(body: str) -> List[str]:
    if not body:
        return []

    text = body.replace("\r", "")
    text = re.sub(r"(?:^|\n)\s*(?:[-*•]|\d+[.)])\s+", "\n", text)

    primary_chunks = [chunk.strip() for chunk in re.split(r"\n{2,}", text) if chunk.strip()]
    segments: List[str] = []

    for chunk in primary_chunks:
        lines = [line.strip() for line in chunk.split("\n") if line.strip()]
        current: List[str] = []
        for line in lines:
            if _looks_like_new_record(line) and current:
                segments.append(" ".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            segments.append(" ".join(current))

    final_segments: List[str] = []
    for segment in segments:
        parts = _SEMICOLON_SPLIT.split(segment)
        for part in parts:
            if not part.strip():
                continue
            slash_parts = _SLASH_SPLIT.split(part)
            if len(slash_parts) > 1:
                final_segments.append(" ".join(slash_parts).strip())
            else:
                final_segments.append(part.strip())

    return final_segments or [body.strip()]


def _product_matches(segment: str) -> List[Tuple[str, int, int]]:
    synonyms = config_loader.get_synonyms().get("product", {})
    if not synonyms:
        return []
    pattern = re.compile(
        r"(?<![\w/%])(" + "|".join(sorted((re.escape(k) for k in synonyms.keys()), key=len, reverse=True)) + r")(?!(?:[%\w]))",
        re.IGNORECASE,
    )
    matches: List[Tuple[str, int, int]] = []
    for match in pattern.finditer(segment):
        canonical = synonyms.get(match.group(1).lower())
        if not canonical:
            continue
        matches.append((canonical, match.start(), match.end()))
    matches.sort(key=lambda item: item[1])
    deduped: List[Tuple[str, int, int]] = []
    seen: set[str] = set()
    for canonical, start, end in matches:
        key = (canonical, start)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((canonical, start, end))
    return deduped


def detect_products(segment: str) -> List[str]:
    return [item[0] for item in _product_matches(segment)]


def _nearest_product(products: List[Tuple[str, int, int]], index: int) -> Optional[str]:
    closest: Tuple[int, Optional[str]] = (10**9, None)
    for name, start, end in products:
        distance = min(abs(index - start), abs(index - end))
        if distance < closest[0]:
            closest = (distance, name)
    return closest[1]


def _parse_float(token: str) -> Optional[float]:
    if not token:
        return None
    cleaned = token.replace(",", "").strip()
    multiplier = 1.0
    if cleaned.lower().endswith("k"):
        multiplier = 1000.0
        cleaned = cleaned[:-1]
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def parse_qty(segment: str, products: Optional[List[str]] = None) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    per_product: Dict[str, Dict[str, Any]] = defaultdict(dict)
    matches_products = _product_matches(segment)
    if products:
        ordered = [p for p in matches_products if p[0] in products]
        if ordered:
            matches_products = ordered

    range_spans: List[Tuple[int, int]] = []
    for match in _RANGE_PATTERN.finditer(segment):
        context_window = segment[max(0, match.start() - 10) : match.start()].lower()
        if "eta" in context_window or "lay" in context_window:
            continue
        trailing = segment[match.end() : match.end() + 5].lower()
        if "+" in trailing:
            continue
        qty_min = _parse_float(match.group("min"))
        qty_max = _parse_float(match.group("max"))
        if qty_min is None or qty_max is None:
            continue
        product = _nearest_product(matches_products, match.start())
        if not re.search(_QTY_UNITS, match.group(0), re.IGNORECASE) and not product:
            continue
        range_spans.append((match.start(), match.end()))
        target = per_product[product] if product else results
        target["qty_min_mt"] = qty_min
        target["qty_max_mt"] = qty_max

    def overlaps_range(start: int, end: int) -> bool:
        return any(start >= r_start and end <= r_end for r_start, r_end in range_spans)

    for match in _SINGLE_QTY_PATTERN.finditer(segment):
        if overlaps_range(match.start(), match.end()):
            continue
        qty = _parse_float(match.group("qty"))
        if qty is None:
            continue
        product = _nearest_product(matches_products, match.start())
        target = per_product[product] if product else results
        if "qty_mt" not in target:
            target["qty_mt"] = qty

    if per_product:
        results["per_product"] = dict(per_product)
    return results


def _strip_quantity_text(segment: str) -> str:
    cleaned = segment
    for match in _RANGE_PATTERN.finditer(segment):
        text = match.group(0)
        if re.search(_QTY_UNITS, text, re.IGNORECASE):
            cleaned = cleaned.replace(text, " ")
    for match in _SINGLE_QTY_PATTERN.finditer(segment):
        cleaned = cleaned.replace(match.group(0), " ")
    return cleaned


def _supplier_from_context(text: str) -> Optional[str]:
    synonyms = config_loader.get_synonyms().get("supplier", {})
    if not synonyms:
        synonyms = config_loader.get_synonyms().get("buyer", {})
    if not synonyms:
        return None
    for match in re.finditer(
        r"(" + "|".join(sorted((re.escape(k) for k in synonyms.keys()), key=len, reverse=True)) + r")",
        text,
        flags=re.IGNORECASE,
    ):
        canonical = synonyms.get(match.group(1).lower())
        if canonical:
            return canonical
    return None


def parse_prices_and_fees(segment: str, products: Optional[List[str]] = None) -> Dict[str, Any]:
    cleaned_segment = _strip_quantity_text(segment)
    results: Dict[str, Any] = {}
    per_product: Dict[str, Dict[str, Any]] = defaultdict(dict)
    matches_products = _product_matches(segment)
    if products:
        matches_products = [p for p in matches_products if p[0] in products]

    slash_match = _PRICE_SLASH_PATTERN.search(cleaned_segment)
    if slash_match and matches_products:
        values = [slash_match.group("a"), slash_match.group("b")]
        for idx, product in enumerate(matches_products[: len(values)]):
            per_product[product[0]]["price_usd_mt"] = _parse_float(values[idx])
        remainder = cleaned_segment[slash_match.end():]
        fee_match = re.search(r"\+(?P<fee>[\d.,]+(?:[kK])?)", remainder)
        if fee_match:
            fee = _parse_float(fee_match.group("fee"))
            if fee is not None:
                results["barging_fee_usd"] = fee

    if "price_usd_mt" not in results and not per_product:
        keyword_candidates: List[Tuple[str, float, int]] = []
        for match in _PRICE_WITH_KEYWORD.finditer(cleaned_segment):
            token = match.group(0).lower()
            value = _parse_float(match.group("value"))
            if value is None:
                continue
            if "barg" in cleaned_segment[match.start(): match.end() + 10].lower():
                continue
            keyword_candidates.append((token, value, match.start()))
        selected: Optional[Tuple[str, float, int]] = None
        for token, value, idx in keyword_candidates:
            if any(key in token for key in ("done", "sold", "offer", "@")):
                selected = (token, value, idx)
                break
        if not selected and keyword_candidates:
            selected = keyword_candidates[0]
        if selected:
            results["price_usd_mt"] = selected[1]

    for match in _SUPPLIER_PRICE_PATTERN.finditer(cleaned_segment):
        supplier_candidate = match.group("supplier").strip().upper()
        if supplier_candidate in {"DONE", "SOLD", "OFFER"}:
            continue
        if "AGENT" in supplier_candidate or "BROKER" in supplier_candidate:
            continue
        price_value = _parse_float(match.group("value"))
        if price_value is None:
            continue
        supplier = _supplier_from_context(supplier_candidate)
        if not supplier and supplier_candidate:
            supplier = supplier_candidate
        if supplier and "supplier" not in results:
            results["supplier"] = supplier
        if per_product:
            product = _nearest_product(matches_products, match.start())
            target = per_product[product] if product else results
        else:
            target = results
        if "price_usd_mt" not in target:
            target["price_usd_mt"] = price_value

    barging_match = _BARGING_PATTERN.search(cleaned_segment)
    if barging_match:
        fee = _parse_float(barging_match.group("value"))
        if fee is not None:
            results["barging_fee_usd"] = fee

    premium_match = _PREMIUM_PATTERN.search(cleaned_segment)
    if premium_match:
        premium = _parse_float(premium_match.group("value"))
        if premium is not None:
            results["premium_usd_mt"] = premium

    if per_product:
        results["per_product"] = dict(per_product)

    return results


def _assign_range(target: Dict[str, Any], start: datetime, end: datetime, prefix: str) -> None:
    target[f"{prefix}_start"] = start.date().isoformat()
    target[f"{prefix}_end"] = end.date().isoformat()


def _parse_date(value: str, default_year: int) -> Optional[datetime]:
    try:
        parsed = date_parser.parse(value, dayfirst=False, yearfirst=False, default=datetime(default_year, 1, 1, tzinfo=SG_TZ))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SG_TZ)
        return parsed
    except (ValueError, TypeError):
        return None


def parse_dates(segment: str, fallback_year: Optional[int]) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    year = fallback_year or datetime.now(tz=SG_TZ).year
    matches: List[Tuple[int, int, datetime, datetime]] = []

    for match in _DATE_RANGE_YMD.finditer(segment):
        start = _parse_date(match.group("start"), year)
        end = _parse_date(match.group("end"), year)
        if start and end:
            matches.append((match.start(), match.end(), start, end))

    for match in _DATE_RANGE_DAY_MONTH.finditer(segment):
        month = match.group("month")
        start_value = f"{match.group('start_day')} {month} {year}"
        end_value = f"{match.group('end_day')} {month} {year}"
        start = _parse_date(start_value, year)
        end = _parse_date(end_value, year)
        if start and end:
            matches.append((match.start(), match.end(), start, end))

    for match in _ISO_DATE_PATTERN.finditer(segment):
        date_value = _parse_date(match.group(0), year)
        if date_value:
            matches.append((match.start(), match.end(), date_value, date_value))

    for match in _SINGLE_DATE_MONTH.finditer(segment):
        month = match.group("month")
        year_token = match.group("year")
        resolved_year = year
        if year_token:
            year_int = int(year_token)
            if year_int < 100:
                year_int += 2000 if year_int < 50 else 1900
            resolved_year = year_int
        date_value = _parse_date(f"{match.group('day')} {month} {resolved_year}", resolved_year)
        if date_value:
            matches.append((match.start(), match.end(), date_value, date_value))

    for match in _MONTH_FIRST_PATTERN.finditer(segment):
        month = match.group("month")
        year_token = match.group("year")
        resolved_year = year
        if year_token:
            year_int = int(year_token)
            if year_int < 100:
                year_int += 2000 if year_int < 50 else 1900
            resolved_year = year_int
        date_value = _parse_date(f"{match.group('day')} {month} {resolved_year}", resolved_year)
        if date_value:
            matches.append((match.start(), match.end(), date_value, date_value))

    matches.sort(key=lambda item: item[0])

    for start_idx, end_idx, start_dt, end_dt in matches:
        prefix = "eta"
        context = segment[max(0, start_idx - 20):start_idx].lower()
        if "laycan" in context:
            prefix = "laycan"
        elif "eta" in context:
            prefix = "eta"
        elif "lay" in context:
            prefix = "laycan"
        if f"{prefix}_start" in results and prefix == "eta":
            prefix = "laycan"
        _assign_range(results, start_dt, end_dt, prefix)

    return results


def _resolve_counterparty(token: str) -> Optional[str]:
    synonyms = config_loader.get_synonyms().get("buyer", {})
    if not synonyms:
        return None
    canonical = synonyms.get(token.lower())
    if canonical:
        return canonical
    for key, value in sorted(synonyms.items(), key=lambda item: len(item[0]), reverse=True):
        if key in token.lower():
            return value
    return token.upper() if token else None


def parse_parties_and_status(segment: str) -> Dict[str, Any]:
    results: Dict[str, Any] = {"status": "UNKNOWN"}
    lower = segment.lower()

    for keyword, mapped in _STATUS_MAP.items():
        if keyword in lower:
            results["status"] = mapped
            break

    def _resolve_from_text(text: str) -> Optional[str]:
        parts = text.split()
        for length in range(len(parts), 0, -1):
            candidate = " ".join(parts[-length:])
            resolved = _resolve_counterparty(candidate)
            if resolved:
                return resolved
        return None

    buyer_matches = re.findall(r"-\s*([A-Za-z&'\s]{2,})", segment)
    for match in buyer_matches:
        candidate = match
        for stop in (" AGENT", " BROKER", " SOLD", " DONE", " ETA", " LAYCAN"):
            idx = candidate.upper().find(stop)
            if idx != -1:
                candidate = candidate[:idx]
        candidate = candidate.strip().upper()
        if not candidate:
            continue
        resolved = _resolve_from_text(candidate)
        if resolved:
            results.setdefault("buyer", resolved)

    agent_match = re.search(r"agent\s+([A-Za-z&'\s]{2,})", segment, flags=re.IGNORECASE)
    if agent_match:
        agent_candidate = agent_match.group(1).strip().upper()
        resolved_agent = _resolve_from_text(agent_candidate)
        results["agent"] = resolved_agent or agent_candidate

    for broker_match in re.finditer(r"([A-Za-z&'\s]{2,})\s*-\s*[A-Za-z]", segment):
        left_tokens = broker_match.group(1).strip().split()
        if not left_tokens:
            continue
        for length in range(min(len(left_tokens), 3), 0, -1):
            candidate_text = " ".join(left_tokens[-length:])
            resolved = _resolve_from_text(candidate_text)
            if resolved and resolved not in {results.get("buyer"), results.get("agent")}:
                results["broker"] = resolved
                break
        if "broker" in results:
            break

    supplier = _supplier_from_context(segment)
    if supplier:
        resolved_supplier = _resolve_from_text(supplier) or supplier
        results.setdefault("supplier", resolved_supplier)

    return results


def parse_port_and_basis(segment: str) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    port_synonyms = config_loader.get_synonyms().get("port", {})
    for synonym, canonical in port_synonyms.items():
        if synonym and synonym in segment.lower():
            results["port"] = canonical
            break

    basis_match = re.search(r"\b\d+(?:\s*[+-]\s*\d+){1,}\b", segment)
    if not basis_match:
        basis_match = re.search(r"\b\d+-\d+-\d+\b", segment)
    if basis_match:
        results["pricing_basis"] = basis_match.group(0)

    return results


def _base_record() -> Dict[str, Any]:
    return {field.name: (field.default if field.default is not None else None) for field in config_loader.get_field_definitions()}


def extract_records(text: str) -> List[Dict[str, Any]]:
    body, meta = strip_chat_header(text)
    segments = split_candidates(body)
    records: List[Dict[str, Any]] = []
    fallback_year = None
    if "message_ts" in meta and meta["message_ts"]:
        try:
            fallback_year = date_parser.isoparse(meta["message_ts"]).year
        except (ValueError, TypeError):
            fallback_year = None

    for segment in segments:
        products = detect_products(segment)
        qty_info = parse_qty(segment, products)
        price_info = parse_prices_and_fees(segment, products)
        date_info = parse_dates(segment, fallback_year)
        parties_info = parse_parties_and_status(segment)
        port_info = parse_port_and_basis(segment)

        base = _base_record()
        base.update(meta)
        base.update({k: v for k, v in parties_info.items() if v is not None})
        base.update({k: v for k, v in port_info.items() if v is not None})
        base.update({k: v for k, v in date_info.items() if v is not None})
        base.update({k: v for k, v in price_info.items() if k != "per_product" and v is not None})
        base.update({k: v for k, v in qty_info.items() if k != "per_product" and v is not None})
        base["source"] = base.get("source") or "whatsapp"

        per_qty = qty_info.get("per_product", {}) if isinstance(qty_info.get("per_product"), dict) else {}
        per_price = price_info.get("per_product", {}) if isinstance(price_info.get("per_product"), dict) else {}

        if products:
            for product in products:
                record = dict(base)
                record["product"] = product
                if product in per_qty:
                    record.update({k: v for k, v in per_qty[product].items() if v is not None})
                if product in per_price:
                    record.update({k: v for k, v in per_price[product].items() if v is not None})
                record["__segment__"] = segment
                records.append(record)
        else:
            base["__segment__"] = segment
            records.append(base)

    return records


__all__ = [
    "strip_chat_header",
    "split_candidates",
    "detect_products",
    "parse_qty",
    "parse_prices_and_fees",
    "parse_dates",
    "parse_parties_and_status",
    "parse_port_and_basis",
    "extract_records",
]
