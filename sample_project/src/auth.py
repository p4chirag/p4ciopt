"""Tiny auth module (sample-project demo target)."""
import hashlib
import secrets


def hash_password(password: str, salt: str = "demo-salt") -> str:
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def check_password(password: str, hashed: str, salt: str = "demo-salt") -> bool:
    return hash_password(password, salt) == hashed


def generate_token(n_bytes: int = 16) -> str:
    return secrets.token_hex(n_bytes)


def is_authorized(user_role: str, required_role: str) -> bool:
    hierarchy = {"guest": 0, "user": 1, "admin": 2}
    return hierarchy.get(user_role, -1) >= hierarchy.get(required_role, 99)
