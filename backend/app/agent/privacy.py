"""Deterministic privacy policy for deciding whether a request may use cloud LLMs.

This module intentionally makes no model calls. Model judgment can interpret a
request, but only fixed policy code decides which providers may receive it.
"""

import re


_SENSITIVE_CONTEXT = re.compile(
    r"\b(?:private|confidential|sensitive|personal data|personally identifiable|"
    r"medical|health|diagnosis|patient|therapy|financial|bank|banking|credit card|"
    r"tax return|social security|national id|passport|password|passphrase|secret|"
    r"api key|access token|authentication token|credential|salary|payroll|"
    r"client records|customer records|company confidential|trade secret)\b"
    r"|व्यक्तिगत|निजी|गोप्य|गोपनीय|स्वास्थ्य|चिकित्सा|बैंक|पासवर्ड|"
    r"निजी|गोप्य|स्वास्थ्य|बैंक|पासवर्ड",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER_OR_KEY = re.compile(
    r"\b(?:bearer\s+[A-Z0-9._~+/-]{12,}|(?:api[_ -]?key|access[_ -]?token|password)\s*[:=]\s*\S{6,})\b",
    re.IGNORECASE,
)
_CARD_NUMBER = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def should_keep_local(user_text: str) -> bool:
    """Return whether fixed privacy rules require local-only processing.

    Requests that contain common sensitive-data terms, email addresses,
    credential-like values, or payment-card-shaped numbers stay local. The
    request's explicit ``private=True`` flag is enforced separately by the LLM
    provider layer and always takes precedence.
    """
    text = str(user_text or "")
    return any(pattern.search(text) for pattern in (_SENSITIVE_CONTEXT, _EMAIL, _BEARER_OR_KEY, _CARD_NUMBER))
