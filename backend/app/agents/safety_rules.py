"""Deterministic, non-LLM safety screening.

This is the hard code-level guardrail required by the safety boundary: it
runs as plain Python pattern matching, independent of any model's
cooperation, so it cannot be talked around by a prompt. The Safety Agent
(an LlmAgent, see safety_agent.py) provides a second, more nuanced layer on
top of this one — but this module alone is sufficient to block the obvious
cases even if the LLM step is skipped, misconfigured, or fails.
"""

import re

from app.db.models import EscalationReason

_EMERGENCY_PATTERNS = [
    r"\bchest pain\b",
    r"\bcan\W?t breathe\b",
    r"\bcannot breathe\b",
    r"\bdifficulty breathing\b",
    r"\bnot breathing\b",
    r"\bsuicidal\b",
    r"\bkill myself\b",
    r"\bkill himself\b",
    r"\bkill herself\b",
    r"\bself[\s-]?harm\b",
    r"\bsevere(ly)? bleeding\b",
    r"\bbleeding (heavily|uncontrollably)\b",
    r"\bunconscious\b",
    r"\bheart attack\b",
    r"\bstroke\b",
    r"\boverdose\b",
    r"\bemergency\b",
    r"\bcall(ing)? 911\b",
    r"\b911\b",
    r"\bambulance\b",
]

_DIAGNOSIS_OR_PRESCRIPTION_PATTERNS = [
    r"\bdiagnose me\b",
    r"\bdo i have (cancer|diabetes|covid|copd|als|a tumor|hiv)\b",
    r"\bwhat disease do i have\b",
    r"\bwhat('s| is) wrong with me\b",
    r"\bwhat condition do i have\b",
    r"\bam i dying\b",
    r"\bis (it|this) (serious|cancer|fatal)\b",
    r"\bprescribe me\b",
    r"\bcan you prescribe\b",
    r"\bwrite me a prescription\b",
    r"\bhow many (mg|milligrams|pills|tablets) should i take\b",
    r"\bwhat dosage\b",
    r"\bincrease my dos(e|age)\b",
    r"\bdecrease my dos(e|age)\b",
    r"\bwhich medication should i take\b",
    r"\bwhat medicine should i take\b",
]


def screen_text(text: str) -> dict:
    """Scan free text for emergency or diagnosis/prescription-seeking language.

    Returns a structured verdict; never mutates anything — callers decide
    what to do (create an Escalation, halt a pipeline, etc.).
    """
    if not text:
        return {"is_unsafe": False, "category": None, "matched_phrase": None}

    lowered = text.lower()

    for pattern in _EMERGENCY_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            return {
                "is_unsafe": True,
                "category": EscalationReason.EMERGENCY_LANGUAGE,
                "matched_phrase": match.group(0),
            }

    for pattern in _DIAGNOSIS_OR_PRESCRIPTION_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            return {
                "is_unsafe": True,
                "category": EscalationReason.DIAGNOSIS_OR_PRESCRIPTION_REQUEST,
                "matched_phrase": match.group(0),
            }

    return {"is_unsafe": False, "category": None, "matched_phrase": None}
