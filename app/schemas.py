"""Pydantic models shared by the API, the analyst and the store."""
from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

PHONE_RE = re.compile(r"^\d{7,12}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

Speaker = Literal["customer", "agent", "unknown"]
Sentiment = Literal["Positive", "Neutral", "Negative"]
SafetyCategory = Literal[
    "none",
    "sexual_content",
    "danger",
    "data_theft",
    "prompt_injection",
    "abuse",
    "other",
]
Severity = Literal["none", "low", "medium", "high"]


# ---------------------------------------------------------------- customer
class CustomerInfo(BaseModel):
    """Everything the agent must capture before the call panel unlocks."""

    phone: str = Field(min_length=7, max_length=12)
    full_name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120)
    product: str = Field(min_length=2, max_length=80)
    agent_name: str = Field(min_length=2, max_length=60)

    # Optional enrichment (autofilled from the demographics file)
    gender: Optional[str] = None
    age: Optional[int] = None
    state: Optional[str] = None
    region: Optional[str] = None
    income_group: Optional[str] = None
    education: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        if not PHONE_RE.match(v):
            raise ValueError("Phone must be 7-12 digits")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v

    @field_validator("full_name", "product", "agent_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Too short")
        return v


# ---------------------------------------------------------------- transcript
class TranscriptLine(BaseModel):
    speaker: Speaker
    text: str


class AudioSegment(BaseModel):
    start: float
    end: float
    text: str


class VoiceSignal(BaseModel):
    """Acoustic features measured from the audio (not from the words)."""

    duration_sec: float = 0
    speech_ratio: float = 0  # fraction of time with speech
    words_per_min: float = 0
    energy_variability: float = 0  # std/mean of RMS energy
    loudness_db: float = 0  # mean RMS in dBFS
    pitch_mean_hz: float = 0
    pitch_variability: float = 0  # std/mean of F0
    pause_count: int = 0
    longest_pause_sec: float = 0
    interpretation: str = ""  # short rule-based description


class NewMaterial(BaseModel):
    """What was added to the call since the last analysis."""

    kind: Literal["text", "audio"]
    speaker: Speaker = "customer"
    text: str = ""
    language_hint: str = ""
    segments: List[AudioSegment] = Field(default_factory=list)
    voice_signal: Optional[VoiceSignal] = None


class AnalyzeRequest(BaseModel):
    call_id: Optional[str] = None
    customer: CustomerInfo
    prior_transcript: List[TranscriptLine] = Field(default_factory=list)
    new_material: NewMaterial


# ---------------------------------------------------------------- LLM output
class SafetyAssessment(BaseModel):
    category: SafetyCategory
    severity: Severity
    description: str
    keywords: List[str]
    agent_guidance: str
    block_solutions: bool


class SolutionOption(BaseModel):
    title: str
    details: str
    suggested_phrasing: str
    kind: Literal["immediate", "follow_up", "escalation"]


class CallAnalysis(BaseModel):
    """Structured output produced by Claude for every analysis pass."""

    transcript: List[TranscriptLine]
    detected_language: str
    summary: str
    problem_statement: str
    customer_goal: str
    sentiment: Sentiment
    sentiment_keywords: List[str]
    emotional_effect: str
    voice_tone: str
    priority_score: int
    priority_keywords: List[str]
    urgent_action: str
    next_question: str
    solutions: List[SolutionOption]
    recommended_solution_index: int
    safety: SafetyAssessment


class ReportInsights(BaseModel):
    """Structured output for the analytics report."""

    executive_summary: str
    key_findings: List[str]
    staffing_recommendations: List[str]
    demographic_support_insights: List[str]
    technical_friction_areas: List[str]
    operational_priorities: List[str]
    executive_action_plan: str


# ---------------------------------------------------------------- store
class CallRecord(BaseModel):
    id: str
    phone: str
    date: str
    time: str
    status: Literal["open", "closed"] = "open"
    customer: Optional[CustomerInfo] = None
    agent_name: str = ""
    input_mode: str = "text"
    selected_solutions: List[int] = Field(default_factory=list)
    agent_notes: str = ""
    outcome: str = ""
    data: dict


class SelectSolutionRequest(BaseModel):
    solution_index: int
    offered: bool = True


class CloseCallRequest(BaseModel):
    outcome: str = ""
    agent_notes: str = ""
