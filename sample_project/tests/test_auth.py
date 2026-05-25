from src.auth import check_password, generate_token, hash_password, is_authorized


def test_password_check():
    hashed = hash_password("hunter2")
    assert check_password("hunter2", hashed)
    assert not check_password("wrong", hashed)


def test_user_auth():
    # This test is the "high correlation with src/auth.py changes" demo pattern.
    hashed = hash_password("p@ss")
    assert check_password("p@ss", hashed)


def test_token_gen():
    t1 = generate_token()
    t2 = generate_token()
    assert t1 != t2
    assert len(t1) == 32


def test_is_authorized():
    assert is_authorized("admin", "user")
    assert is_authorized("user", "user")
    assert not is_authorized("guest", "admin")
