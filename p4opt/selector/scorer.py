"""Combine path-mapping, historical-correlation, and static-import-graph
signals into a ranked list.

Final score = PATH_WEIGHT * path_score
            + HISTORY_WEIGHT * history_score
            + IMPORT_WEIGHT * import_graph_score
(all three signals normalized to [0, 1])

This module also exposes the top-level `select_tests` entry point.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from p4opt.selector.correlator import historical_scores
from p4opt.selector.import_graph import import_scores
from p4opt.selector.mapper import path_scores, discover_tests

PATH_WEIGHT = 0.4
HISTORY_WEIGHT = 0.3
IMPORT_WEIGHT = 0.3
DEFAULT_THRESHOLD = 0.2


@dataclass
class ScoredTest:
    test_id: str
    score: float
    reasons: tuple[str, ...]

    def __iter__(self):
        yield self.test_id
        yield self.score
        yield self.reasons


def select_tests(
    changed_files: list[str],
    project_root: Path,
    conn: sqlite3.Connection | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[ScoredTest]:
    """Return tests ranked by combined score, filtered by threshold.

    Args:
        changed_files: list of changed file paths (relative to project_root or depot paths)
        project_root: project root for discovering tests
        conn: SQLite connection (optional; if None, historical signal is skipped)
        threshold: minimum combined score to include

    Returns:
        Ranked list of ScoredTest, highest score first.
    """
    all_tests = discover_tests(project_root)
    if not all_tests:
        return []

    path_map = path_scores(changed_files, all_tests, project_root)
    history_map = historical_scores(changed_files, all_tests, conn) if conn else {}
    import_map = import_scores(changed_files, all_tests, project_root)

    scored: list[ScoredTest] = []
    for test_id in all_tests:
        p = path_map.get(test_id, 0.0)
        h = history_map.get(test_id, 0.0)
        i_score, i_reason = import_map.get(test_id, (0.0, ""))
        combined = (
            PATH_WEIGHT * p
            + HISTORY_WEIGHT * h
            + IMPORT_WEIGHT * i_score
        )
        if combined < threshold:
            continue
        reasons: list[str] = []
        if p > 0:
            reasons.append(f"path match ({p:.2f})")
        if h > 0:
            reasons.append(f"historical correlation ({h:.2f})")
        if i_score > 0:
            reasons.append(i_reason)
        scored.append(ScoredTest(test_id=test_id, score=combined, reasons=tuple(reasons)))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored
