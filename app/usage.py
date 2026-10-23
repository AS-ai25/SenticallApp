"""Token usage + cost accounting for every Claude call.

Prices are USD per million tokens (Anthropic first-party API, October 2026).
Cache reads/writes fall back to 0.1x / 1.25x of the input price when a model
has no explicit entry. Update PRICES if Anthropic changes the price list.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Dict, List, Optional

from . import config

PRICES: Dict[str, Dict[str, float]] = {
    #                      input   output  cache_read  cache_write
    "claude-haiku-5-5":   {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "claude-haiku-4-5":   {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "claude-sonnet-5-5":  {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-sonnet-5":    {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-sonnet-4-6":  {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-5-5":    {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-opus-5":      {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-8":    {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-7":    {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-6":    {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-fable-5-1":   {"input": 10.00, "output": 50.00, "cache_read": 0.25, "cache_write": 12.50},
    "claude-fable-5":     {"input": 10.00, "output": 50.00, "cache_read": 1.00, "cache_write": 12.50},
}

USAGE_PATH = config.DATA_DIR / "usage.jsonl"
_lock = threading.Lock()
_session: List[dict] = []  # entries since the server started
SERVER_STARTED = datetime.now().isoformat(timespec="seconds")


def price_for(model: str) -> Optional[Dict[str, float]]:
    if model in PRICES:
        return PRICES[model]
    # tolerate dated / aliased ids such as "claude-opus-5-5-20260401"
    for key in sorted(PRICES, key=len, reverse=True):
        if model.startswith(key):
            return PRICES[key]
    return None


def cost_usd(model: str, input_tokens: int, output_tokens: int,
             cache_read: int = 0, cache_write: int = 0) -> Optional[float]:
    p = price_for(model)
    if not p:
        return None
    return round(
        (input_tokens * p["input"] + output_tokens * p["output"]
         + cache_read * p["cache_read"] + cache_write * p["cache_write"]) / 1_000_000,
        6,
    )


def record(kind: str, model: str, usage, call_id: str = "", seconds: float = 0.0) -> dict:
    """Persist one API call. `usage` is the SDK's response.usage object."""
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    cr = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cw = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "model": model,
        "call_id": call_id,
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_tokens": cr,
        "cache_write_tokens": cw,
        "total_tokens": inp + out + cr + cw,
        "seconds": round(seconds, 2),
        "cost_usd": cost_usd(model, inp, out, cr, cw),
        "priced": price_for(model) is not None,
    }
    with _lock:
        _session.append(entry)
        with open(USAGE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _read_all() -> List[dict]:
    rows: List[dict] = []
    if USAGE_PATH.exists():
        with open(USAGE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return rows


def _totals(rows: List[dict]) -> dict:
    t = {"calls": len(rows), "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
         "cache_write_tokens": 0, "total_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0}
    for r in rows:
        for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "total_tokens"):
            t[k] += int(r.get(k, 0) or 0)
        if r.get("cost_usd") is None:
            t["unpriced_calls"] += 1
        else:
            t["cost_usd"] += float(r["cost_usd"])
    t["cost_usd"] = round(t["cost_usd"], 6)
    return t


def _breakdown(rows: List[dict], key: str) -> List[dict]:
    groups: Dict[str, List[dict]] = {}
    for r in rows:
        groups.setdefault(str(r.get(key, "")), []).append(r)
    out = []
    for name, rs in sorted(groups.items(), key=lambda kv: -_totals(kv[1])["cost_usd"]):
        out.append({key: name, **_totals(rs)})
    return out


def summary(last: int = 25) -> dict:
    with _lock:
        session = list(_session)
    all_rows = _read_all()
    return {
        "server_started": SERVER_STARTED,
        "current_model": config.MODEL,
        "current_price": price_for(config.MODEL),
        "session": _totals(session),
        "all_time": _totals(all_rows),
        "by_model": _breakdown(all_rows, "model"),
        "by_kind": _breakdown(all_rows, "kind"),
        "recent": list(reversed(all_rows[-last:])),
        "prices": PRICES,
    }


def reset_all() -> int:
    with _lock:
        n = len(_read_all())
        if USAGE_PATH.exists():
            USAGE_PATH.unlink()
        _session.clear()
    return n
