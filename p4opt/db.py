"""SQLite schema and connection helpers for P4CIOptimizer.

Schema (single file, no migrations needed for a hackathon):

  changesets(id TEXT PK, vcs TEXT, ref_from TEXT, ref_to TEXT, created_at TIMESTAMP)
  change_files(changeset_id TEXT, file_path TEXT, PRIMARY KEY(changeset_id, file_path))
  test_runs(id INTEGER PK AUTOINCREMENT,
            run_group TEXT,            -- groups all tests that ran together
            changeset_id TEXT,         -- nullable; ties run to a changeset
            test_id TEXT,              -- pytest node id, e.g. tests/test_foo.py::test_bar
            duration_ms REAL,
            status TEXT,               -- passed | failed | skipped | error
            run_at TIMESTAMP)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_FILENAME = "p4opt.db"


def db_path(root: Path | str | None = None) -> Path:
    root = Path(root) if root else Path.cwd()
    return root / DB_FILENAME


def connect(
    root: Path | str | None = None,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(root), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS changesets (
    id          TEXT PRIMARY KEY,
    vcs         TEXT NOT NULL,
    ref_from    TEXT,
    ref_to      TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS change_files (
    changeset_id TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    PRIMARY KEY (changeset_id, file_path),
    FOREIGN KEY (changeset_id) REFERENCES changesets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS test_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_group     TEXT NOT NULL,
    changeset_id  TEXT,
    test_id       TEXT NOT NULL,
    duration_ms   REAL NOT NULL,
    status        TEXT NOT NULL,
    run_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_test_runs_test_id  ON test_runs(test_id);
CREATE INDEX IF NOT EXISTS idx_test_runs_run_at   ON test_runs(run_at);
CREATE INDEX IF NOT EXISTS idx_test_runs_cs       ON test_runs(changeset_id);
CREATE INDEX IF NOT EXISTS idx_change_files_path  ON change_files(file_path);
"""


def init_db(root: Path | str | None = None) -> None:
    with connect(root) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def cursor(root: Path | str | None = None):
    conn = connect(root)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
