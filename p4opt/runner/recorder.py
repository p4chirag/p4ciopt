"""Persist changesets and test runs to SQLite."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from p4opt.runner.pytest_runner import RunResult
from p4opt.vcs.base import Changeset


def record_changeset(conn: sqlite3.Connection, cs: Changeset) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO changesets (id, vcs, ref_from, ref_to)
           VALUES (?, ?, ?, ?)""",
        (cs.id, cs.vcs, cs.ref_from, cs.ref_to),
    )
    for f in cs.files:
        # Normalize depot paths for consistent lookup
        normed = f.replace("\\", "/")
        if normed.startswith("//"):
            parts = normed.split("/", 3)
            normed = parts[3] if len(parts) > 3 else normed
        conn.execute(
            """INSERT OR IGNORE INTO change_files (changeset_id, file_path)
               VALUES (?, ?)""",
            (cs.id, normed),
        )


def record_run(
    conn: sqlite3.Connection,
    result: RunResult,
    changeset_id: str | None = None,
    run_at: datetime | None = None,
) -> str:
    """Persist all outcomes from a RunResult, sharing one run_group id.

    Returns the run_group id (useful for joining the run together).
    """
    run_group = uuid.uuid4().hex[:12]
    ts = run_at.isoformat(sep=" ", timespec="seconds") if run_at else None
    for o in result.outcomes:
        if ts is not None:
            conn.execute(
                """INSERT INTO test_runs
                   (run_group, changeset_id, test_id, duration_ms, status, run_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (run_group, changeset_id, o.test_id, o.duration_ms, o.status, ts),
            )
        else:
            conn.execute(
                """INSERT INTO test_runs
                   (run_group, changeset_id, test_id, duration_ms, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (run_group, changeset_id, o.test_id, o.duration_ms, o.status),
            )
    return run_group
