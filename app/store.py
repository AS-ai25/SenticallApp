"""JSON-lines persistence for calls plus demographics lookup."""
from __future__ import annotations

import csv
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from .schemas import CallRecord

_lock = threading.Lock()


# ---------------------------------------------------------------- demographics
_demo_cache: Optional[Dict[str, dict]] = None


def load_demographics(path: Path = config.DEMOGRAPHICS_PATH) -> Dict[str, dict]:
    global _demo_cache
    if _demo_cache is not None and path == config.DEMOGRAPHICS_PATH:
        return _demo_cache
    out: Dict[str, dict] = {}
    if path.exists():
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                phone = (row.get("phone") or "").strip()
                if phone:
                    out[phone] = row
    if path == config.DEMOGRAPHICS_PATH:
        _demo_cache = out
    return out


def lookup_customer(phone: str) -> Optional[dict]:
    """Return enrichment data for ONE phone number only (never lists)."""
    row = load_demographics().get(phone.strip())
    if not row:
        return None
    try:
        age = int(row.get("age") or 0) or None
    except ValueError:
        age = None
    return {
        "phone": phone,
        "gender": row.get("gender") or None,
        "age": age,
        "state": row.get("state") or None,
        "region": row.get("region") or None,
        "income_group": row.get("incomeGroup") or None,
        "education": row.get("education") or None,
        "product": row.get("product_purchased") or None,
    }


# ---------------------------------------------------------------- calls
def _read_jsonl(path: Path) -> List[dict]:
    rows: List[dict] = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _write_jsonl(path: Path, rows: List[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def load_demo_calls() -> List[dict]:
    rows = _read_jsonl(config.DEMO_CALLS_PATH)
    for r in rows:
        r.setdefault("source", "demo")
        r.setdefault("status", "closed")
    return rows


def load_live_calls() -> List[dict]:
    rows = _read_jsonl(config.LIVE_CALLS_PATH)
    for r in rows:
        r.setdefault("source", "live")
    return rows


def all_calls() -> List[dict]:
    return load_demo_calls() + load_live_calls()


def new_call_id() -> str:
    return f"CONV-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3]}"


def upsert_call(record: CallRecord) -> CallRecord:
    with _lock:
        rows = load_live_calls()
        payload = record.model_dump()
        payload["source"] = "live"
        for i, r in enumerate(rows):
            if r.get("id") == record.id:
                rows[i] = payload
                break
        else:
            rows.append(payload)
        _write_jsonl(config.LIVE_CALLS_PATH, rows)
    return record


def get_call(call_id: str) -> Optional[dict]:
    for r in load_live_calls():
        if r.get("id") == call_id:
            return r
    return None


def update_call(call_id: str, **changes) -> Optional[dict]:
    with _lock:
        rows = load_live_calls()
        target = None
        for r in rows:
            if r.get("id") == call_id:
                r.update(changes)
                target = r
                break
        if target is None:
            return None
        _write_jsonl(config.LIVE_CALLS_PATH, rows)
    return target


def clear_live_calls() -> int:
    with _lock:
        n = len(load_live_calls())
        if config.LIVE_CALLS_PATH.exists():
            config.LIVE_CALLS_PATH.unlink()
    return n
