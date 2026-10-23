"""Senticall API + static frontend."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import analyst, analytics, config, store, stt, usage
from .guardrails import screen_text
from .schemas import (
    AnalyzeRequest,
    CallRecord,
    CloseCallRequest,
    CustomerInfo,
    SelectSolutionRequest,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("senticall")

app = FastAPI(title="Senticall", version="2.0.0")

_insights_cache: dict = {}


# ---------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    calls = store.all_calls()
    return {
        "ok": True,
        "model": config.MODEL,
        "api_key": config.api_key_present(),
        "whisper_model": config.WHISPER_MODEL,
        "whisper_device": stt.device_info(),
        "calls": len(calls),
        "live_calls": sum(1 for c in calls if c.get("source") == "live"),
    }


# ---------------------------------------------------------------- customers
@app.get("/api/customers/lookup")
def customer_lookup(phone: str):
    phone = phone.strip()
    if not phone.isdigit() or not 7 <= len(phone) <= 12:
        raise HTTPException(400, "Phone must be 7-12 digits")
    found = store.lookup_customer(phone)
    return {"found": found is not None, "customer": found or {"phone": phone}}


@app.post("/api/customers/validate")
def customer_validate(customer: dict):
    try:
        CustomerInfo(**customer)
        return {"valid": True, "errors": {}}
    except ValidationError as e:
        errors = {}
        for err in e.errors():
            loc = err["loc"][0] if err["loc"] else "customer"
            errors[str(loc)] = err["msg"].replace("Value error, ", "")
        return {"valid": False, "errors": errors}


# ---------------------------------------------------------------- stt
ALLOWED_AUDIO = {".wav", ".mp3", ".m4a", ".ogg", ".opus", ".webm", ".flac", ".aac", ".mp4"}


@app.post("/api/stt")
async def speech_to_text(file: UploadFile = File(...), language: str = Form("")):
    suffix = Path(file.filename or "audio").suffix.lower() or ".webm"
    if suffix not in ALLOWED_AUDIO:
        raise HTTPException(400, f"Unsupported audio type {suffix}")
    dest = config.UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    try:
        result = stt.transcribe(str(dest), language=language.strip() or None)
        signal = stt.voice_signal(str(dest), result["segments"], result["duration"])
    except Exception as e:
        log.exception("stt failed")
        raise HTTPException(500, f"Transcription failed: {e}")
    finally:
        try:
            dest.unlink()
        except OSError:
            pass
    return {
        "language": result["language"],
        "language_probability": round(result["language_probability"], 3),
        "duration": round(result["duration"], 2),
        "segments": [s.model_dump() for s in result["segments"]],
        "voice_signal": signal.model_dump(),
        "whisper_device": stt.device_info(),
    }


# ---------------------------------------------------------------- live analysis
@app.post("/api/calls/analyze")
def analyze(req: AnalyzeRequest):
    if not config.api_key_present():
        raise HTTPException(503, "ANTHROPIC_API_KEY is not configured on the server.")
    nm = req.new_material
    if nm.kind == "text" and not nm.text.strip():
        raise HTTPException(400, "Empty text.")
    if nm.kind == "audio" and not nm.segments:
        raise HTTPException(400, "No speech was detected in the audio.")

    analyst.last_usage = None
    try:
        analysis = analyst.analyze_call(req)
    except anthropic.AuthenticationError:
        raise HTTPException(503, "Anthropic API key rejected.")
    except anthropic.RateLimitError:
        raise HTTPException(429, "Anthropic rate limit reached. Try again in a moment.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Anthropic API error: {e.message}")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Could not reach the Anthropic API.")

    call_id = req.call_id or store.new_call_id()
    existing = store.get_call(call_id) if req.call_id else None
    now = datetime.now()
    record = CallRecord(
        id=call_id,
        phone=req.customer.phone,
        date=existing["date"] if existing else now.strftime("%Y-%m-%d"),
        time=existing["time"] if existing else now.strftime("%H:%M:%S"),
        status="open",
        customer=req.customer,
        agent_name=req.customer.agent_name,
        input_mode=nm.kind,
        selected_solutions=existing.get("selected_solutions", []) if existing else [],
        agent_notes=existing.get("agent_notes", "") if existing else "",
        data=analysis.model_dump(),
    )
    store.upsert_call(record)
    return {"call_id": call_id, "analysis": analysis.model_dump(), "record": record.model_dump(),
            "usage": analyst.last_usage}


@app.post("/api/calls/{call_id}/select")
def select_solution(call_id: str, body: SelectSolutionRequest):
    rec = store.get_call(call_id)
    if not rec:
        raise HTTPException(404, "Call not found")
    sel = list(rec.get("selected_solutions", []))
    if body.offered and body.solution_index not in sel:
        sel.append(body.solution_index)
    if not body.offered and body.solution_index in sel:
        sel.remove(body.solution_index)
    store.update_call(call_id, selected_solutions=sel)
    return {"call_id": call_id, "selected_solutions": sel}


@app.post("/api/calls/{call_id}/close")
def close_call(call_id: str, body: CloseCallRequest):
    rec = store.update_call(call_id, status="closed", outcome=body.outcome, agent_notes=body.agent_notes)
    if not rec:
        raise HTTPException(404, "Call not found")
    return {"call_id": call_id, "status": "closed"}


@app.get("/api/calls")
def list_calls(limit: int = 200):
    return {"calls": analytics.history(limit)}


@app.get("/api/calls/{call_id}")
def get_call(call_id: str):
    for r in store.all_calls():
        if r.get("id") == call_id:
            return r
    raise HTTPException(404, "Call not found")


@app.delete("/api/calls/live")
def clear_live():
    n = store.clear_live_calls()
    _insights_cache.clear()
    return {"deleted": n}


@app.post("/api/screen")
def screen(body: dict):
    """Expose the regex pre-screen so the UI can warn while the agent types."""
    res = screen_text(str(body.get("text", "")))
    return {"category": res.category, "matches": res.matches, "all": res.all_categories}


# ---------------------------------------------------------------- usage / cost
@app.get("/api/usage")
def usage_summary(last: int = 25):
    return usage.summary(last=last)


@app.delete("/api/usage")
def usage_reset():
    return {"deleted": usage.reset_all()}


# ---------------------------------------------------------------- analytics
@app.get("/api/analytics/dashboard")
def dashboard():
    return analytics.dashboard()


def _dash_hash(dash: dict) -> str:
    return hashlib.sha1(json.dumps(dash, sort_keys=True, default=str).encode()).hexdigest()


@app.post("/api/report/insights")
def report_insights(force: bool = False):
    if not config.api_key_present():
        raise HTTPException(503, "ANTHROPIC_API_KEY is not configured on the server.")
    dash = analytics.dashboard()
    if dash.get("total_calls") == 0 or not dash.get("kpis"):
        raise HTTPException(400, "No call data to analyse.")
    key = _dash_hash(dash)
    if not force and key in _insights_cache:
        return {"insights": _insights_cache[key], "cached": True, "usage": None}
    analyst.last_usage = None
    try:
        ins = analyst.report_insights(analytics.report_input(dash))
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Anthropic API error: {e.message}")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Could not reach the Anthropic API.")
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    _insights_cache[key] = ins.model_dump()
    return {"insights": _insights_cache[key], "cached": False, "usage": analyst.last_usage}


@app.post("/api/report/pptx")
def report_pptx():
    from .report_pptx import build_pptx
    from .schemas import ReportInsights

    dash = analytics.dashboard()
    if dash.get("total_calls") == 0 or not dash.get("kpis"):
        raise HTTPException(400, "No call data to export.")
    key = _dash_hash(dash)
    ins: Optional[ReportInsights] = None
    if key in _insights_cache:
        ins = ReportInsights(**_insights_cache[key])
    path = build_pptx(dash, ins)
    return {"file": path.name, "url": f"/exports/{path.name}", "with_insights": ins is not None}


@app.get("/exports/{name}")
def download_export(name: str):
    path = (config.EXPORT_DIR / name).resolve()
    if path.parent != config.EXPORT_DIR.resolve() or not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path, filename=name)


@app.get("/api/sample-audio")
def sample_audio():
    p = config.DATA_DIR / "samples" / "customer_call_sample.wav"
    if not p.exists():
        raise HTTPException(404, "Sample not available")
    return FileResponse(p, filename="customer_call_sample.wav", media_type="audio/wav")


# ---------------------------------------------------------------- static
app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")
