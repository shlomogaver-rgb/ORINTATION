"""LocalizationProfile / NotationPolicy - ONE place. Semantics (MEAN, STANDARD_DEVIATION, ...) are the source of truth;
the profile decides the displayed symbol. Solvers/parsers never depend on display notation."""
from __future__ import annotations

import re
from enum import Enum


class Profile(str, Enum):
    ISRAEL_HIGH_SCHOOL = "ISRAEL_HIGH_SCHOOL"
    SOURCE_FAITHFUL = "SOURCE_FAITHFUL"
    GENERIC_MATH = "GENERIC_MATH"


NOTATION_VERSION = "notation/1.0"
DEFAULT_PROFILE = Profile.ISRAEL_HIGH_SCHOOL

RENDER = {
    Profile.ISRAEL_HIGH_SCHOOL: {"MEAN": r"\bar{x}", "STANDARD_DEVIATION": "S", "VARIANCE": "S^2"},
    Profile.GENERIC_MATH: {"MEAN": r"\mu", "STANDARD_DEVIATION": r"\sigma", "VARIANCE": r"\sigma^2"},
}
# every accepted spelling -> semantic entity
ALIASES = [
    (re.compile(r"\\bar\{x\}|\\overline\{x\}|x̄|x̅"), "MEAN"),
    (re.compile(r"\\mu(?![a-zA-Z])|μ"), "MEAN"),
    (re.compile(r"\\sigma\^\{?2\}?|σ\^?2|σ²"), "VARIANCE"),
    (re.compile(r"\\sigma(?![a-zA-Z])|σ"), "STANDARD_DEVIATION"),
]
GENERIC_SYMBOLS = {"MEAN": [r"\mu", "μ"], "STANDARD_DEVIATION": [r"\sigma", "σ"], "VARIANCE": [r"\sigma^2", "σ²", "σ^2"]}
STATS_CONTEXT = re.compile(r"ממוצע|סטיית\s*(?:ה)?תקן|שונות|התפלגות|נורמלי|mean|standard deviation|variance")


def semantic_of(token: str) -> str | None:
    for rx, sem in ALIASES:
        if rx.fullmatch(token.strip()):
            return sem
    words = {"ממוצע": "MEAN", "mean": "MEAN", "mu": "MEAN", "sigma": "STANDARD_DEVIATION", "סטיית תקן": "STANDARD_DEVIATION",
             "standard deviation": "STANDARD_DEVIATION", "שונות": "VARIANCE", "variance": "VARIANCE"}
    return words.get(token.strip().lower())


def display(semantic: str, profile: Profile = DEFAULT_PROFILE, source_symbol: str | None = None) -> str:
    if profile == Profile.SOURCE_FAITHFUL and source_symbol:
        return source_symbol
    return RENDER.get(profile if profile != Profile.SOURCE_FAITHFUL else DEFAULT_PROFILE, RENDER[DEFAULT_PROFILE]).get(semantic, semantic)


def is_statistics(text: str) -> bool:
    return bool(STATS_CONTEXT.search(text or ""))


def apply_profile(text: str, profile: Profile = DEFAULT_PROFILE) -> str:
    """Rewrite generic statistical symbols in GENERATED text to the profile's notation (never in SOURCE_FAITHFUL)."""
    if profile in (Profile.SOURCE_FAITHFUL, Profile.GENERIC_MATH) or not text:
        return text
    t = re.sub(r"\\sigma\^\{?2\}?|σ\^?2|σ²", RENDER[profile]["VARIANCE"], text)
    t = re.sub(r"\\mu(?![a-zA-Z])|μ", lambda m: RENDER[profile]["MEAN"], t)
    t = re.sub(r"\\sigma(?![a-zA-Z])|σ", lambda m: RENDER[profile]["STANDARD_DEVIATION"], t)
    return t


def inconsistencies(texts: dict[str, str], profile: Profile = DEFAULT_PROFILE) -> list[str]:
    """NOTATION_INCONSISTENCY for generated outputs (solutions, rubric, labels) under the profile."""
    if profile == Profile.SOURCE_FAITHFUL:
        return []
    out = []
    for where, t in texts.items():
        for sem, forms in GENERIC_SYMBOLS.items():
            if profile == Profile.ISRAEL_HIGH_SCHOOL and any(f in (t or "") for f in forms):
                out.append(f"NOTATION_INCONSISTENCY: ב{where} מופיע סימון {forms[-1]} במקום {RENDER[profile][sem]} "
                           f"(פרופיל {profile.value}).")
        if profile == Profile.GENERIC_MATH and re.search(r"\\bar\{x\}|x̄", t or ""):
            out.append(f"NOTATION_INCONSISTENCY: ב{where} מופיע \\bar{{x}} בפרופיל GENERIC_MATH.")
    return out
