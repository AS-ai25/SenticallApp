"""Speech-to-text (faster-whisper, local, any language) + acoustic voice signal.

Claude has no audio input, so the pipeline is:
  audio -> whisper (original language text + timestamps)
        -> numeric voice features (energy, pitch, pace, pauses)
        -> both are handed to Claude, which translates, separates speakers
           and interprets the tone.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from . import config
from .schemas import AudioSegment, VoiceSignal

log = logging.getLogger("senticall.stt")

_model = None
_model_lock = threading.Lock()
_device_used: str = "not loaded"


def _register_cuda_dlls() -> None:
    """Windows: make the pip-installed NVIDIA DLLs visible to ctranslate2."""
    if os.name != "nt":
        return
    try:
        import nvidia  # type: ignore

        base = Path(nvidia.__file__).parent
        for sub in ("cublas", "cudnn", "cuda_nvrtc"):
            bin_dir = base / sub / "bin"
            if bin_dir.is_dir():
                os.add_dll_directory(str(bin_dir))
    except Exception:
        pass


def _pick_device() -> Tuple[str, str]:
    want = config.WHISPER_DEVICE
    if want in ("cuda", "gpu"):
        return "cuda", "float16"
    if want == "cpu":
        return "cpu", "int8"
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def get_model():
    global _model, _device_used
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        from faster_whisper import WhisperModel

        _register_cuda_dlls()
        dev, compute = _pick_device()
        try:
            _model = WhisperModel(config.WHISPER_MODEL, device=dev, compute_type=compute)
        except Exception as e:  # fall back to CPU
            log.warning("GPU unavailable for whisper (%s), using CPU", e)
            dev, compute = "cpu", "int8"
            _model = WhisperModel(config.WHISPER_MODEL, device=dev, compute_type=compute)
        _device_used = f"{dev}/{compute}"
        log.info("Whisper %s loaded on %s", config.WHISPER_MODEL, _device_used)
    return _model


def device_info() -> str:
    return _device_used


def transcribe(path: str, language: Optional[str] = None) -> dict:
    """Run whisper. Returns language, probability, duration and segments."""
    model = get_model()
    segments_iter, info = model.transcribe(
        path,
        language=language or None,
        beam_size=5,
        vad_filter=True,
        word_timestamps=False,
    )
    segments: List[AudioSegment] = []
    for seg in segments_iter:
        txt = seg.text.strip()
        if txt:
            segments.append(AudioSegment(start=float(seg.start), end=float(seg.end), text=txt))
    return {
        "language": info.language,
        "language_probability": float(info.language_probability or 0),
        "duration": float(info.duration or 0),
        "segments": segments,
    }


# ---------------------------------------------------------------- acoustics
def _load_mono(path: str, sr: int = 16000) -> Tuple[np.ndarray, int]:
    import librosa

    y, _ = librosa.load(path, sr=sr, mono=True)
    return y.astype(np.float32), sr


def voice_signal(path: str, segments: List[AudioSegment], duration: float) -> VoiceSignal:
    """Measure prosodic features. Rule-based and deliberately conservative."""
    try:
        import librosa

        y, sr = _load_mono(path)
        if y.size == 0:
            return VoiceSignal(duration_sec=duration)
        dur = len(y) / sr
        frame, hop = 1024, 256
        rms = librosa.feature.rms(y=y, frame_length=frame, hop_length=hop)[0]
        rms = rms[rms > 0]
        # loudness statistics on speech frames only (silence would inflate variability)
        speech_rms = rms[rms > np.percentile(rms, 35)] if rms.size else rms
        loud_db = float(20 * np.log10(np.mean(speech_rms) + 1e-9)) if speech_rms.size else -60.0
        energy_var = float(np.std(speech_rms) / (np.mean(speech_rms) + 1e-9)) if speech_rms.size else 0.0

        # Fundamental frequency on voiced frames only (first 3 minutes are enough)
        y_f0 = y[: sr * 180]
        f0 = librosa.yin(y_f0, fmin=70, fmax=400, sr=sr, frame_length=2048, hop_length=1024)
        frame_rms = librosa.feature.rms(y=y_f0, frame_length=2048, hop_length=1024)[0]
        thresh = np.percentile(frame_rms, 60) if frame_rms.size else 0
        voiced = f0[(frame_rms[: len(f0)] > thresh) & (f0 > 70) & (f0 < 400)]
        pitch_mean = float(np.median(voiced)) if voiced.size else 0.0
        pitch_var = float(np.std(voiced) / (np.mean(voiced) + 1e-9)) if voiced.size else 0.0

        # Pauses and pace from whisper segments
        speech = sum(max(0.0, s.end - s.start) for s in segments)
        speech_ratio = float(min(1.0, speech / dur)) if dur else 0.0
        words = sum(len(s.text.split()) for s in segments)
        wpm = float(words / (speech / 60)) if speech > 0 else 0.0
        gaps = [b.start - a.end for a, b in zip(segments, segments[1:])]
        pauses = [g for g in gaps if g >= 0.7]

        notes = []
        if wpm >= 175:
            notes.append("fast speech")
        elif 0 < wpm <= 105:
            notes.append("slow, deliberate speech")
        if energy_var >= 0.75:
            notes.append("strong loudness swings (possible agitation)")
        elif energy_var and energy_var <= 0.3:
            notes.append("flat, steady loudness")
        if pitch_var >= 0.28:
            notes.append("high pitch variability (emotional emphasis)")
        elif 0 < pitch_var <= 0.12:
            notes.append("monotone pitch")
        if pauses and max(pauses) >= 2.5:
            notes.append("long pauses (hesitation or hold time)")
        if loud_db >= -18:
            notes.append("loud")
        elif loud_db <= -34:
            notes.append("quiet / distant")
        return VoiceSignal(
            duration_sec=round(dur, 2),
            speech_ratio=round(speech_ratio, 3),
            words_per_min=round(wpm, 1),
            energy_variability=round(energy_var, 3),
            loudness_db=round(loud_db, 1),
            pitch_mean_hz=round(pitch_mean, 1),
            pitch_variability=round(pitch_var, 3),
            pause_count=len(pauses),
            longest_pause_sec=round(max(pauses), 2) if pauses else 0.0,
            interpretation="; ".join(notes) if notes else "neutral, even delivery",
        )
    except Exception as e:  # never block the call on acoustics
        log.warning("voice signal failed: %s", e)
        return VoiceSignal(duration_sec=duration, interpretation="unavailable")
