from src.strings import capitalize, join_words, lower, reverse, split_words, upper


def test_upper():
    assert upper("abc") == "ABC"


def test_lower():
    assert lower("ABC") == "abc"


def test_capitalize():
    assert capitalize("hello") == "Hello"


def test_reverse():
    assert reverse("abc") == "cba"


def test_split_words():
    assert split_words("a b c") == ["a", "b", "c"]


def test_join_words():
    assert join_words(["a", "b"], "-") == "a-b"
