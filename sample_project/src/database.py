"""Tiny in-memory 'database' (sample-project demo target)."""


class Database:
    def __init__(self):
        self._rows: dict[int, dict] = {}
        self._next_id = 1

    def insert(self, row: dict) -> int:
        rid = self._next_id
        self._rows[rid] = dict(row)
        self._next_id += 1
        return rid

    def query(self, **filters) -> list[dict]:
        out = []
        for rid, row in self._rows.items():
            if all(row.get(k) == v for k, v in filters.items()):
                out.append({"id": rid, **row})
        return out

    def delete(self, rid: int) -> bool:
        return self._rows.pop(rid, None) is not None

    def update(self, rid: int, **fields) -> bool:
        if rid not in self._rows:
            return False
        self._rows[rid].update(fields)
        return True
