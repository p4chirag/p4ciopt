"""Tiny in-memory cache (sample-project demo target)."""


class Cache:
    def __init__(self, max_size: int = 100):
        self._store: dict[str, str] = {}
        self._max_size = max_size

    def set(self, key: str, value: str) -> None:
        if len(self._store) >= self._max_size:
            self._store.pop(next(iter(self._store)))
        self._store[key] = value

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def invalidate(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    def size(self) -> int:
        return len(self._store)
