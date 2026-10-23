"""Aggregations for the analytics dashboard and the report."""
from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import store

SENTIMENT_ORDER = ["Negative", "Neutral", "Positive"]
SENTIMENT_LETTER = {"Negative": "A", "Neutral": "B", "Positive": "C"}

GROUP_VARS = {
    "gender": ["Male", "Female"],
    "ageGroup": ["18-34", "35-54", "55+"],
    "incomeGroup2": ["under $100k", "$100k+"],
    "education": ["High School", "Some College", "Bachelor", "Master", "PhD"],
}
GROUP_LABELS = {
    "gender": "Gender",
    "ageGroup": "Age Group",
    "incomeGroup2": "Income",
    "education": "Education",
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HOURS = list(range(24))


# ---------------------------------------------------------------- recodes
def recode_income(val: Optional[str]) -> Optional[str]:
    if not isinstance(val, str):
        return None
    if val in ("$50,000 to $74,999", "$75,000 to $99,999"):
        return "under $100k"
    if val in ("$100,000 to $124,999", "$125,000 to $149,999", "$150,000 or more"):
        return "$100k+"
    return None


def recode_education(val: Optional[str]) -> Optional[str]:
    if not isinstance(val, str):
        return None
    v = val.lower()
    if "doctorate" in v or "phd" in v:
        return "PhD"
    if "master" in v or "professional" in v:
        return "Master"
    if "bachelor" in v:
        return "Bachelor"
    if "some college" in v or "associate" in v or "vocational" in v:
        return "Some College"
    if "high school" in v:
        return "High School"
    return None


def recode_age(age) -> Optional[str]:
    try:
        a = float(age)
    except (TypeError, ValueError):
        return None
    if math.isnan(a):
        return None
    if a < 18:
        return None
    if a <= 34:
        return "18-34"
    if a <= 54:
        return "35-54"
    return "55+"


# ---------------------------------------------------------------- frame
def _parse_dt(date: str, time: str) -> Optional[pd.Timestamp]:
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return pd.to_datetime(f"{date} {time}", format=fmt)
        except (ValueError, TypeError):
            continue
    return None


def build_frame() -> pd.DataFrame:
    demo = store.load_demographics()
    rows = []
    for r in store.all_calls():
        d = r.get("data", {}) or {}
        phone = str(r.get("phone") or "").strip()
        dem = demo.get(phone, {})
        cust = r.get("customer") or {}
        safety = d.get("safety") or {}
        rows.append({
            "call_id": r.get("id"),
            "source": r.get("source", "demo"),
            "phone": phone,
            "datetime": _parse_dt(r.get("date", ""), r.get("time", "")),
            "sentiment": str(d.get("sentiment", "")).strip().capitalize() or "Neutral",
            "priority_score": d.get("priority_score"),
            "language": d.get("language_type") or d.get("detected_language") or "",
            "summary": d.get("summary", ""),
            "problem": d.get("problem_statement", "") or d.get("summary", ""),
            "urgent_action": d.get("urgent_action", ""),
            "safety_category": safety.get("category", "none") if isinstance(safety, dict) else "none",
            "gender": dem.get("gender") or cust.get("gender"),
            "age": dem.get("age") or cust.get("age"),
            "incomeGroup": dem.get("incomeGroup") or cust.get("income_group"),
            "education_raw": dem.get("education") or cust.get("education"),
            "region": dem.get("region") or cust.get("region"),
            "product": dem.get("product_purchased") or cust.get("product") or "",
            "status": r.get("status", "closed"),
            "agent_name": r.get("agent_name", ""),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["sentiment"] = df["sentiment"].where(df["sentiment"].isin(SENTIMENT_ORDER), "Neutral")
    df["priority_score"] = pd.to_numeric(df["priority_score"], errors="coerce")
    df["ageGroup"] = df["age"].apply(recode_age)
    df["incomeGroup2"] = df["incomeGroup"].apply(recode_income)
    df["education"] = df["education_raw"].apply(recode_education)
    df["month_abbr"] = df["datetime"].dt.strftime("%b")
    df["day_of_week"] = df["datetime"].dt.strftime("%a")
    df["hour"] = df["datetime"].dt.hour
    return df


# ---------------------------------------------------------------- stats
def ztest_larger(c1: int, c2: int, n: int) -> float:
    """One-sided two-proportion z-test p-value: is p1 > p2 ? (same n)."""
    if n == 0 or c1 <= c2:
        return 1.0
    p1, p2 = c1 / n, c2 / n
    pooled = (c1 + c2) / (2 * n)
    se = math.sqrt(pooled * (1 - pooled) * (2 / n))
    if se == 0:
        return 1.0
    z = (p1 - p2) / se
    return float(1 - norm.cdf(z))


def significance_letters(df: pd.DataFrame, col: str, alpha: float = 0.05) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for value, sub in df.dropna(subset=[col]).groupby(col):
        n = len(sub)
        counts = {s: int((sub["sentiment"] == s).sum()) for s in SENTIMENT_ORDER}
        letters = {s: "" for s in SENTIMENT_ORDER}
        for s1 in SENTIMENT_ORDER:
            for s2 in SENTIMENT_ORDER:
                if s1 != s2 and ztest_larger(counts[s1], counts[s2], n) < alpha:
                    letters[s1] += SENTIMENT_LETTER[s2]
        out[str(value)] = letters
    return out


def sentiment_by(df: pd.DataFrame, col: str, order: List[str]) -> dict:
    sub = df.dropna(subset=[col])
    letters = significance_letters(sub, col)
    cats = [c for c in order if c in set(sub[col])]
    series = {}
    counts = {}
    for s in SENTIMENT_ORDER:
        vals = []
        for c in cats:
            g = sub[sub[col] == c]
            vals.append(round(100 * float((g["sentiment"] == s).mean()), 1) if len(g) else 0.0)
        series[s] = vals
    for c in cats:
        counts[c] = int((sub[col] == c).sum())
    return {
        "label": GROUP_LABELS.get(col, col),
        "categories": cats,
        "counts": counts,
        "series": series,
        "letters": {c: letters.get(c, {}) for c in cats},
    }


def sentiment_over_time(df: pd.DataFrame, col: str, order: List) -> dict:
    sub = df.dropna(subset=[col])
    series = {s: [] for s in SENTIMENT_ORDER}
    counts = []
    for o in order:
        g = sub[sub[col] == o]
        counts.append(int(len(g)))
        for s in SENTIMENT_ORDER:
            series[s].append(round(100 * float((g["sentiment"] == s).mean()), 1) if len(g) else None)
    return {"categories": [str(o) for o in order], "counts": counts, "series": series}


_THEME_WORDS = {
    "software / update": ["update", "software", "version", "firmware", "app", "install"],
    "hardware / defect": ["hardware", "noise", "broken", "defect", "damaged", "not working", "malfunction"],
    "connectivity / network": ["wifi", "network", "connect", "internet", "bluetooth", "pairing"],
    "battery / power": ["battery", "charge", "power", "turn on"],
    "account / login": ["account", "login", "password", "email", "sign in"],
    "billing / refund": ["refund", "charge", "billing", "invoice", "payment", "money"],
    "shipping / delivery": ["deliver", "shipping", "shipment", "arrive", "order"],
    "performance / intermittent": ["intermittent", "slow", "freez", "crash", "lag"],
}


def issue_themes(df: pd.DataFrame, top: int = 8) -> List[dict]:
    counter: Counter = Counter()
    for text in (df["problem"].fillna("") + " " + df["summary"].fillna("")).str.lower():
        for theme, words in _THEME_WORDS.items():
            if any(w in text for w in words):
                counter[theme] += 1
    return [{"theme": t, "count": c} for t, c in counter.most_common(top)]


def dashboard() -> dict:
    df = build_frame()
    if df.empty:
        return {"total_calls": 0}
    total = len(df)
    overall = {s: round(100 * float((df["sentiment"] == s).mean()), 1) for s in SENTIMENT_ORDER}
    pr = df["priority_score"].dropna()
    kpis = {
        "total_calls": int(total),
        "live_calls": int((df["source"] == "live").sum()),
        "demo_calls": int((df["source"] == "demo").sum()),
        "negative_pct": overall["Negative"],
        "avg_priority": round(float(pr.mean()), 1) if len(pr) else 0,
        "high_priority_pct": round(100 * float((pr >= 8).mean()), 1) if len(pr) else 0,
        "safety_alerts": int((df["safety_category"] != "none").sum()),
        "open_calls": int((df["status"] == "open").sum()),
        "matched_demographics": int(df["gender"].notna().sum()),
    }
    prio_dist = {str(i): int((pr == i).sum()) for i in range(1, 11)}
    return {
        "kpis": kpis,
        "overall_sentiment": overall,
        "by_group": {col: sentiment_by(df, col, order) for col, order in GROUP_VARS.items()},
        "by_time": {
            "month": sentiment_over_time(df, "month_abbr", MONTHS),
            "day_of_week": sentiment_over_time(df, "day_of_week", DOW),
            "hour": sentiment_over_time(df, "hour", HOURS),
        },
        "priority_distribution": prio_dist,
        "issue_themes": issue_themes(df),
        "languages": df["language"].replace("", "unknown").value_counts().head(8).to_dict(),
        "safety_breakdown": df["safety_category"].value_counts().to_dict(),
    }


def report_input(dash: dict) -> dict:
    """Compact view of the dashboard for the LLM (drops nulls, keeps numbers)."""
    if not dash or dash.get("total_calls") == 0:
        return dash
    by_group = {}
    for col, g in dash["by_group"].items():
        by_group[g["label"]] = {
            c: {s: g["series"][s][i] for s in SENTIMENT_ORDER} | {"n": g["counts"][c]}
            for i, c in enumerate(g["categories"])
        }
    by_time = {}
    for key, t in dash["by_time"].items():
        by_time[key] = {
            c: {s: t["series"][s][i] for s in SENTIMENT_ORDER} | {"n": t["counts"][i]}
            for i, c in enumerate(t["categories"]) if t["counts"][i]
        }
    return {
        "kpis": dash["kpis"],
        "overall_sentiment_pct": dash["overall_sentiment"],
        "sentiment_pct_by_group": by_group,
        "sentiment_pct_by_time": by_time,
        "priority_distribution": dash["priority_distribution"],
        "issue_themes": dash["issue_themes"],
        "languages": dash["languages"],
        "safety_breakdown": dash["safety_breakdown"],
    }


def history(limit: int = 200) -> List[dict]:
    rows = store.all_calls()
    out = []
    for r in reversed(rows[-limit:]):
        d = r.get("data", {}) or {}
        safety = d.get("safety") or {}
        cust = r.get("customer") or {}
        out.append({
            "id": r.get("id"),
            "source": r.get("source", "demo"),
            "status": r.get("status", "closed"),
            "date": r.get("date"),
            "time": r.get("time"),
            "phone": r.get("phone"),
            "customer_name": cust.get("full_name", ""),
            "agent_name": r.get("agent_name", ""),
            "product": cust.get("product", ""),
            "language": d.get("language_type") or d.get("detected_language") or "",
            "sentiment": d.get("sentiment", ""),
            "sentiment_keywords": d.get("sentiment_keywords", []),
            "priority_score": d.get("priority_score"),
            "priority_keywords": d.get("priority_keywords", []),
            "safety_category": safety.get("category", "none") if isinstance(safety, dict) else "none",
            "problem": d.get("problem_statement") or d.get("summary", ""),
            "selected_solutions": r.get("selected_solutions", []),
            "outcome": r.get("outcome", ""),
        })
    return out
