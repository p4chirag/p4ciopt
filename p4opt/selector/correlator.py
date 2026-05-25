"""Historical correlation: P(test fails | file X was in changeset).

Builds a per-file failure rate for each test, looking at all past changesets
recorded in the DB. The output is normalized so the highest correlation for any
test against any changed file becomes that test's score in [0, 1].
"""
from __future__ import annotations

import sqlite3


def historical_scores(
    changed_files: list[str],
    all_tests: list[str],
    conn: sqlite3.Connection,
) -> dict[str, float]:
    """Score each test by historical failure-correlation with the changed files.

    For each (test, changed_file):
        n_total    = # changesets where changed_file appeared
        n_failed   = # of those changesets where the test ran and failed
        rate       = n_failed / n_total (only counted if n_total >= 3)

    Test's final score = max(rate over all changed_files).
    """
    if not changed_files or not all_tests:
        return {}

    norm_files = [_strip_depot(f) for f in changed_files]
    placeholders = ",".join("?" * len(norm_files))

    # For each file, find changesets where it appeared.
    rows = conn.execute(
        f"""
        SELECT cf.file_path AS file_path, cf.changeset_id AS cs_id
        FROM   change_files cf
        WHERE  cf.file_path IN ({placeholders})
        """,
        norm_files,
    ).fetchall()

    by_file: dict[str, set[str]] = {}
    for r in rows:
        by_file.setdefault(r["file_path"], set()).add(r["cs_id"])

    if not by_file:
        return {}

    test_set = set(all_tests)
    scores: dict[str, float] = {}

    for file_path, cs_ids in by_file.items():
        if len(cs_ids) < 3:
            continue
        cs_placeholders = ",".join("?" * len(cs_ids))
        # For each test that failed in any of these changesets, count failures
        fail_rows = conn.execute(
            f"""
            SELECT test_id, COUNT(DISTINCT changeset_id) AS n_failed
            FROM   test_runs
            WHERE  changeset_id IN ({cs_placeholders})
              AND  status = 'failed'
            GROUP BY test_id
            """,
            list(cs_ids),
        ).fetchall()
        total = len(cs_ids)
        for fr in fail_rows:
            test_id = fr["test_id"]
            # Match by either node-id or by file prefix (so 'tests/test_foo.py::test_x'
            # and 'tests/test_foo.py' both resolve)
            matched = _match_test(test_id, test_set)
            if matched is None:
                continue
            rate = fr["n_failed"] / total
            scores[matched] = max(scores.get(matched, 0.0), rate)

    return scores


def _strip_depot(path: str) -> str:
    p = path.replace("\\", "/")
    if p.startswith("//"):
        parts = p.split("/", 3)
        p = parts[3] if len(parts) > 3 else p
    return p


def _match_test(test_id: str, test_set: set[str]) -> str | None:
    """Map a recorded pytest node-id back to a discovered test file."""
    file_part = test_id.split("::", 1)[0]
    if file_part in test_set:
        return file_part
    # try posix normalization
    normed = file_part.replace("\\", "/")
    if normed in test_set:
        return normed
    return None
