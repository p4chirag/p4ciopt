from src.cache import Cache


def test_cache_set_get():
    c = Cache()
    c.set("a", "1")
    assert c.get("a") == "1"


def test_cache_invalidation():
    # This test is the "flaky test" demo pattern when seeded.
    c = Cache()
    c.set("k", "v")
    assert c.invalidate("k") is True
    assert c.get("k") is None


def test_cache_eviction():
    c = Cache(max_size=2)
    c.set("a", "1")
    c.set("b", "2")
    c.set("c", "3")
    assert c.size() == 2
    assert c.get("a") is None


def test_cache_missing():
    assert Cache().get("nope") is None
