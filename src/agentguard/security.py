from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b", re.I),
    re.compile(r"\b(reveal|print|show|repeat)\s+(the\s+)?(system|developer)\s+prompt\b", re.I),
    re.compile(r"\b(bypass|disable|override)\s+(the\s+)?(policy|guardrails?|safety)\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+(dan|unrestricted|unfiltered)\b", re.I),
)

_EXFILTRATION_PATTERNS = (
    re.compile(
        r"\b(send|upload|post|forward|exfiltrate)\b.{0,80}"
        r"\b(secret|credential|password|api[-_ ]?key|access[-_ ]?token|private[-_ ]?key)s?\b",
        re.I | re.S,
    ),
    re.compile(r"(?:^|[/\\])\.env(?:$|\b)", re.I),
    re.compile(r"(?:^|[/\\])etc[/\\](?:passwd|shadow)(?:$|\b)", re.I),
    re.compile(r"\bBEGIN (?:RSA |OPENSSH )?PRIVATE KEY\b", re.I),
)


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        strings: list[str] = []
        for key, nested in value.items():
            strings.extend(_walk_strings(str(key)))
            strings.extend(_walk_strings(nested))
        return strings
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        strings = []
        for nested in value:
            strings.extend(_walk_strings(nested))
        return strings
    return []


def detect_risk_signals(*values: Any) -> list[str]:
    """Return stable, de-duplicated attack categories found in nested input."""
    text = "\n".join(part for value in values for part in _walk_strings(value))
    signals: list[str] = []
    if any(pattern.search(text) for pattern in _PROMPT_INJECTION_PATTERNS):
        signals.append("prompt_injection")
    if any(pattern.search(text) for pattern in _EXFILTRATION_PATTERNS):
        signals.append("data_exfiltration")
    return signals
