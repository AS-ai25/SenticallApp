# Senticall — Customer Service Intelligence

Real-time assistant for contact-centre agents plus an analytics report, rebuilt as a standalone
app (no Colab) from the BIU DS20 final project.

* **Live Assist** — while the customer is on the line the agent records / uploads / types the
  conversation (any language). Whisper transcribes locally, Claude translates to English,
  separates **customer** and **agent**, states the exact problem, scores priority (1–10),
  flags the urgent action, proposes solutions with a ready-to-say phrasing, and the agent clicks
  **Offer** to log what was proposed.
* **Guardrails** — the call panel is **locked** until every customer field is complete and
  valid; every input is pre-screened (regex) and assessed by Claude for *sexual content*,
  *danger / threats / self-harm*, *data theft / social engineering*, *prompt injection* and
  *abuse*; when flagged the UI shows a red/amber banner with handling guidance and only safe
  handling steps are listed.
* **Analytics & Report** — sentiment by gender / age / income / education (with significance
  letters), by month / weekday / hour, priority distribution, issue themes, AI executive summary
  + strategic recommendations, and a one-click PowerPoint export.

## Stack

FastAPI + vanilla JS/Chart.js frontend · Anthropic Claude (`claude-opus-5-5` by default,
structured outputs) · faster-whisper (local, GPU if available) · librosa voice features ·
pandas/scipy analytics · python-pptx export · JSON-lines storage.

## Run

```bash
pip install -r requirements.txt
copy .env.example .env      # put your ANTHROPIC_API_KEY in .env
python -m uvicorn app.main:app --port 8050
```

or double-click `START.bat`, then open http://127.0.0.1:8050.

`.env` keys: `ANTHROPIC_API_KEY`, `SENTICALL_MODEL` (e.g. `claude-sonnet-5-5` or
`claude-haiku-5-5` for faster live analysis), `WHISPER_MODEL` (`small` default, `large-v3` for
best multilingual accuracy), `WHISPER_DEVICE` (`auto|cuda|cpu`).

## Data

* `data/customer_demographics.csv` — customer base used for the phone look-up (one record per phone,
  never listed).
* `data/demo_calls.jsonl` — the 60 analysed calls from the original project (read-only demo data for
  the dashboard).
* `data/calls.jsonl` — live calls created by the app (git-ignored).
* `data/samples/customer_call_sample.wav` — sample call ("Use sample call" button).

## Tests

```bash
python -m pytest -q
```

## Layout

```
app/
  main.py        FastAPI routes + static mount
  analyst.py     Claude prompts, structured output (CallAnalysis / ReportInsights)
  guardrails.py  regex pre-screen + agent guidance per category
  stt.py         faster-whisper transcription + acoustic voice signal
  analytics.py   dashboard aggregations, z-test significance letters, themes
  report_pptx.py PowerPoint builder
  store.py       JSONL persistence + demographics lookup
  schemas.py     Pydantic models
static/          index.html, styles.css, app.js
tests/           pytest suite (LLM + Whisper mocked)
```
