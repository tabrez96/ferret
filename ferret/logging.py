"""Log redaction: secrets, emails and card-like numbers never reach the logs."""

import logging
import re
import sys

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_PAIR = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|refresh_token|api_key|dek|kek|key|authorization|cookie)"
    r"\b([\"']?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CARD_NUMBER = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-+/=]{40,}")


def redact(text: str) -> str:
    text = _BEARER.sub("Bearer <redacted>", text)
    text = _SECRET_PAIR.sub(r"\1\2<redacted>", text)
    text = _EMAIL.sub("<email>", text)
    text = _CARD_NUMBER.sub("<number>", text)
    return _LONG_TOKEN.sub("<redacted>", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(level: str | int = "INFO") -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_ferret", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler._ferret = True  # type: ignore[attr-defined]
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
