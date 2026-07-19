"""
Lightweight, dependency-free PII redaction for log previews.

Deliberately conservative and pattern-based rather than ML-based: it's
applied to *log previews only* (never to the actual chat content shown to
the user, and never to what's sent to the LLM), so false positives cost
nothing but a slightly-over-redacted debug string, while false negatives
leak real PII into logs. Bias toward over-redaction.
"""

import re

_PATTERNS = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("phone", re.compile(r"\+?\d{1,3}[-.\s]?\(?\d{3,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}")),
    ("credit_card", re.compile(r"(?:\d[ -]*?){13,16}")),
    ("ssn", re.compile(r"\d{3}-\d{2}-\d{4}")),
    ("api_key", re.compile(r"\b(?:sk|pk)-[A-Za-z0-9]{16,}\b")),
]

_MAX_PREVIEW_LENGTH = 300


def redact_pii(text: str) -> str:
    if not text:
        return text
    redacted = text
    for name, pattern in _PATTERNS:
        redacted = pattern.sub(f"[REDACTED_{name.upper()}]", redacted)
    return redacted


def to_preview(text: str) -> str:
    redacted = redact_pii(text)
    if len(redacted) <= _MAX_PREVIEW_LENGTH:
        return redacted
    return redacted[:_MAX_PREVIEW_LENGTH] + "…"
