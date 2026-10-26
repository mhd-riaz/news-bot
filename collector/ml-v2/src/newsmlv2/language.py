"""Deterministic language detection shared by the classifier and snapshot builder."""

from __future__ import annotations

from . import config
from .admit import non_latin_share


def detect_language(text: str) -> tuple[str, float]:
    from langdetect import DetectorFactory, LangDetectException, detect_langs

    if non_latin_share(text) > 0.15:
        return "und", 0.0
    DetectorFactory.seed = config.SEED
    try:
        detected = detect_langs(text[:1500])
    except LangDetectException:
        return "und", 0.0
    if not detected:
        return "und", 0.0
    best = detected[0]
    return best.lang, float(best.prob)
