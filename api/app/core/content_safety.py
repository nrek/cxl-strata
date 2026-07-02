"""Simple payload checks to keep STRATA from becoming a secret sink."""

from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:api[_-]?key|secret|password|token)\s*[:=]\s*[^\s,;]{8,}", re.I),
)

REDACTION_TEXT = "[REDACTED_SECRET]"


def find_secret_markers(value: Any) -> list[str]:
    text = _flatten(value)
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]


def redact_secret_markers(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(_redaction_for_match, redacted)
    return redacted


def reject_if_secrets(value: Any) -> None:
    if find_secret_markers(value):
        raise ValueError("Content appears to contain secrets")


def _redaction_for_match(match: re.Match[str]) -> str:
    text = match.group(0)
    prefix = re.match(r"(?P<key>\b(?:api[_-]?key|secret|password|token)\s*[:=]\s*)", text, re.I)
    if prefix:
        return f"{prefix.group('key')}{REDACTION_TEXT}"
    return REDACTION_TEXT


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return "\n".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return "\n".join(_flatten(v) for v in value)
    return str(value)
