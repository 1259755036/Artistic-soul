import json
import sqlite3
import threading
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schemas import RecordStatus

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "records.db"

_lock = threading.RLock()
_connection: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
    return _connection


def init_db() -> None:
    with _lock:
        conn = get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL,
                parsed_json TEXT NOT NULL,
                status TEXT NOT NULL,
                reasons TEXT NOT NULL,
                hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def compute_hash(record: Dict[str, Any]) -> str:
    fingerprint = json.dumps(record, sort_keys=True)
    return sha256(fingerprint.encode("utf-8")).hexdigest()


def save_record(raw_text: str, parsed: Dict[str, Any], status: RecordStatus, reasons: List[str]) -> int:
    with _lock:
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        record_hash = compute_hash(parsed)
        conn.execute(
            "INSERT INTO records(raw_text, parsed_json, status, reasons, hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (raw_text, json.dumps(parsed, sort_keys=True), status.value, json.dumps(reasons), record_hash, now, now),
        )
        conn.commit()
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def find_by_hash(record_hash: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM records WHERE hash=?", (record_hash,)).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def update_record(record_id: int, parsed: Dict[str, Any], status: RecordStatus, reasons: Optional[List[str]] = None) -> None:
    with _lock:
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE records SET parsed_json=?, status=?, reasons=?, updated_at=? WHERE id=?",
            (
                json.dumps(parsed, sort_keys=True),
                status.value,
                json.dumps(reasons or []),
                now,
                record_id,
            ),
        )
        conn.commit()


def fetch_record(record_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def list_records(status: Optional[RecordStatus] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    if status:
        rows = conn.execute("SELECT * FROM records WHERE status=? ORDER BY created_at DESC", (status.value,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM records ORDER BY created_at DESC").fetchall()
    return [_row_to_dict(row) for row in rows]


def log_event(message: str) -> None:
    with _lock:
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        conn.execute("INSERT INTO logs(message, created_at) VALUES (?, ?)", (message, now))
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "raw_text": row["raw_text"],
        "parsed": json.loads(row["parsed_json"]),
        "status": RecordStatus(row["status"]),
        "reasons": json.loads(row["reasons"] or "[]"),
        "hash": row["hash"],
        "created_at": datetime.fromisoformat(row["created_at"]),
        "updated_at": datetime.fromisoformat(row["updated_at"]),
    }
