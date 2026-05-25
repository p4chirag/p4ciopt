"""Tiny validators (sample-project demo target)."""
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[\d\s\-()]{7,}$")
URL_RE = re.compile(r"^https?://[^\s]+$")


def is_email(s: str) -> bool:
    return bool(EMAIL_RE.match(s))


def is_phone(s: str) -> bool:
    return bool(PHONE_RE.match(s))


def is_url(s: str) -> bool:
    return bool(URL_RE.match(s))


def is_valid_age(age: int) -> bool:
    return 0 <= age <= 150


def is_strong_password(p: str) -> bool:
    return (
        len(p) >= 8
        and any(c.isupper() for c in p)
        and any(c.islower() for c in p)
        and any(c.isdigit() for c in p)
    )
