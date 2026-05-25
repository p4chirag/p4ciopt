from src.validators import (
    is_email, is_phone, is_strong_password, is_url, is_valid_age,
)


def test_email_valid():
    assert is_email("a@b.co")


def test_email_invalid():
    assert not is_email("nope")


def test_phone_valid():
    assert is_phone("+1 (555) 123-4567")


def test_phone_invalid():
    assert not is_phone("abc")


def test_url_valid():
    assert is_url("https://example.com")


def test_url_invalid():
    assert not is_url("ftp://no")


def test_age_valid():
    assert is_valid_age(30)


def test_age_invalid():
    assert not is_valid_age(-1)
    assert not is_valid_age(200)


def test_password_strength():
    assert is_strong_password("Abcdef1!")
    assert not is_strong_password("weak")
