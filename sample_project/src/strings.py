"""Tiny string helpers (sample-project demo target)."""


def upper(s: str) -> str:
    return s.upper()


def lower(s: str) -> str:
    return s.lower()


def capitalize(s: str) -> str:
    return s.capitalize()


def reverse(s: str) -> str:
    return s[::-1]


def split_words(s: str) -> list[str]:
    return s.split()


def join_words(words: list[str], sep: str = " ") -> str:
    return sep.join(words)
