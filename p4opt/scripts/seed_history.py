"""Populate the SQLite history with synthetic but realistic data for the demo.

Bakes in three demo patterns (deterministic with --seed):
  1. DEGRADING : tests/test_database.py::test_database_query
                 — duration ramps 200ms -> 850ms over the window.
  2. FLAKY     : tests/test_cache.py::test_cache_invalidation
                 — passes ~70% of the time.
  3. CORRELATED: tests/test_auth.py::test_user_auth
                 — fails ~75% of the time when src/auth.py is in the changeset.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from p4opt import db as dbmod

TESTS = [
    ("tests/test_auth.py",        "test_password_check"),
    ("tests/test_auth.py",        "test_user_auth"),
    ("tests/test_auth.py",        "test_token_gen"),
    ("tests/test_auth.py",        "test_is_authorized"),
    ("tests/test_cache.py",       "test_cache_set_get"),
    ("tests/test_cache.py",       "test_cache_invalidation"),
    ("tests/test_cache.py",       "test_cache_eviction"),
    ("tests/test_cache.py",       "test_cache_missing"),
    ("tests/test_database.py",    "test_database_query"),
    ("tests/test_database.py",    "test_db_insert"),
    ("tests/test_database.py",    "test_db_delete"),
    ("tests/test_database.py",    "test_db_update"),
    ("tests/test_database.py",    "test_db_transaction"),
    ("tests/test_calculator.py",  "test_add"),
    ("tests/test_calculator.py",  "test_subtract"),
    ("tests/test_calculator.py",  "test_multiply"),
    ("tests/test_calculator.py",  "test_divide"),
    ("tests/test_calculator.py",  "test_divide_by_zero"),
    ("tests/test_calculator.py",  "test_modulo"),
    ("tests/test_calculator.py",  "test_power"),
    ("tests/test_strings.py",     "test_upper"),
    ("tests/test_strings.py",     "test_lower"),
    ("tests/test_strings.py",     "test_capitalize"),
    ("tests/test_strings.py",     "test_reverse"),
    ("tests/test_strings.py",     "test_split_words"),
    ("tests/test_strings.py",     "test_join_words"),
    ("tests/test_validators.py",  "test_email_valid"),
    ("tests/test_validators.py",  "test_email_invalid"),
    ("tests/test_validators.py",  "test_phone_valid"),
    ("tests/test_validators.py",  "test_phone_invalid"),
    ("tests/test_validators.py",  "test_url_valid"),
    ("tests/test_validators.py",  "test_url_invalid"),
    ("tests/test_validators.py",  "test_age_valid"),
    ("tests/test_validators.py",  "test_age_invalid"),
    ("tests/test_validators.py",  "test_password_strength"),
]

SOURCE_FILES = [
    "src/auth.py",
    "src/cache.py",
    "src/database.py",
    "src/calculator.py",
    "src/strings.py",
    "src/validators.py",
]

# Patterns
DEGRADING       = "tests/test_database.py::test_database_query"
FLAKY           = "tests/test_cache.py::test_cache_invalidation"
CORRELATED_FILE = "src/auth.py"
CORRELATED_TEST = "tests/test_auth.py::test_user_auth"

# Base per-test duration profile (ms)
BASE_MS = {
    "tests/test_auth.py::test_password_check": 25.0,
    "tests/test_auth.py::test_user_auth":      30.0,
    "tests/test_auth.py::test_token_gen":      8.0,
    "tests/test_auth.py::test_is_authorized":  3.0,
    "tests/test_cache.py::test_cache_set_get":     5.0,
    "tests/test_cache.py::test_cache_invalidation":7.0,
    "tests/test_cache.py::test_cache_eviction":    10.0,
    "tests/test_cache.py::test_cache_missing":     3.0,
    "tests/test_database.py::test_db_insert":      8.0,
    "tests/test_database.py::test_db_delete":      8.0,
    "tests/test_database.py::test_db_update":      9.0,
    "tests/test_database.py::test_db_transaction": 18.0,
}


def _duration(test_id: str, day_progress: float, rng: random.Random) -> float:
    if test_id == DEGRADING:
        # 200 -> 850 ms linear with some noise
        base = 200.0 + 650.0 * day_progress
        return max(50.0, base + rng.uniform(-20.0, 20.0))
    base = BASE_MS.get(test_id, rng.uniform(2.0, 15.0))
    return max(0.5, base + rng.uniform(-base * 0.15, base * 0.15))


def _status(test_id: str, files_in_cs: list[str], rng: random.Random) -> str:
    if test_id == FLAKY:
        return "failed" if rng.random() < 0.30 else "passed"
    if test_id == CORRELATED_TEST and CORRELATED_FILE in files_in_cs:
        return "failed" if rng.random() < 0.75 else "passed"
    return "failed" if rng.random() < 0.015 else "passed"


def seed_history(project_root: Path, days: int = 60, rng_seed: int = 42) -> int:
    """Wipe and reseed the test_runs history. Returns rows inserted."""
    project_root = Path(project_root)
    dbmod.init_db(project_root)
    rng = random.Random(rng_seed)
    now = datetime.utcnow()
    n_rows = 0

    with dbmod.cursor(project_root) as conn:
        conn.execute("DELETE FROM test_runs")
        conn.execute("DELETE FROM change_files")
        conn.execute("DELETE FROM changesets WHERE id LIKE 'seed:%'")

        for day_offset in range(days, 0, -1):
            day_progress = (days - day_offset) / max(1, days - 1)
            run_date = now - timedelta(days=day_offset)
            n_changesets = rng.randint(3, 6)

            for cs_idx in range(n_changesets):
                n_files = rng.randint(1, 3)
                files = rng.sample(SOURCE_FILES, n_files)
                cs_id = f"seed:{run_date.strftime('%Y%m%d')}-{cs_idx}"

                conn.execute(
                    """INSERT OR REPLACE INTO changesets
                       (id, vcs, ref_from, ref_to) VALUES (?, ?, ?, ?)""",
                    (cs_id, "git", None, None),
                )
                for f in files:
                    conn.execute(
                        """INSERT OR IGNORE INTO change_files
                           (changeset_id, file_path) VALUES (?, ?)""",
                        (cs_id, f),
                    )

                run_at = run_date.replace(
                    hour=rng.randint(8, 18),
                    minute=rng.randint(0, 59),
                    second=rng.randint(0, 59),
                    microsecond=0,
                )
                run_group = uuid.uuid4().hex[:12]

                for file_part, test_name in TESTS:
                    test_id = f"{file_part}::{test_name}"
                    dur = _duration(test_id, day_progress, rng)
                    status = _status(test_id, files, rng)
                    conn.execute(
                        """INSERT INTO test_runs
                           (run_group, changeset_id, test_id,
                            duration_ms, status, run_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            run_group, cs_id, test_id,
                            dur, status,
                            run_at.isoformat(sep=" ", timespec="seconds"),
                        ),
                    )
                    n_rows += 1
    return n_rows


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=str(Path.cwd()))
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    n = seed_history(Path(args.project), days=args.days, rng_seed=args.seed)
    print(f"Seeded {n} test runs across {args.days} days.")
