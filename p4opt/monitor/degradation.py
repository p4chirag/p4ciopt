"""Test health: degrading runtime, slow tests, flaky tests.

A test is:
  - DEGRADING if linear regression of duration over time has positive slope
    above a threshold (ms/day) with statistical significance (p < 0.05) and
    at least 10 data points in the window.
  - SLOW     if its median duration is above the suite p95 threshold.
  - FLAKY    if its pass-rate over the last N runs is between 0.10 and 0.90.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from scipy.stats import linregress

WINDOW_DAYS = 30
MIN_POINTS = 10
SLOPE_MS_PER_DAY = 5.0
P_VALUE = 0.05
FLAKY_WINDOW = 20
FLAKY_LOW = 0.10
FLAKY_HIGH = 0.90


@dataclass
class DegradingTest:
    test_id: str
    slope_ms_per_day: float
    p_value: float
    n_points: int
    first_ms: float
    last_ms: float


@dataclass
class SlowTest:
    test_id: str
    median_ms: float
    p95_threshold: float


@dataclass
class FlakyTest:
    test_id: str
    pass_rate: float
    n_runs: int


@dataclass
class HealthReport:
    degrading: list[DegradingTest]
    slow: list[SlowTest]
    flaky: list[FlakyTest]


def _fetch_recent(
    conn: sqlite3.Connection, days: int
) -> dict[str, list[tuple[datetime, float, str]]]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat(sep=" ", timespec="seconds")
    rows = conn.execute(
        """SELECT test_id, run_at, duration_ms, status
           FROM   test_runs
           WHERE  run_at >= ?
           ORDER  BY test_id, run_at""",
        (cutoff,),
    ).fetchall()
    grouped: dict[str, list[tuple[datetime, float, str]]] = {}
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["run_at"])
        except (TypeError, ValueError):
            continue
        grouped.setdefault(r["test_id"], []).append((ts, float(r["duration_ms"]), r["status"]))
    return grouped


def detect_degrading(conn: sqlite3.Connection) -> list[DegradingTest]:
    grouped = _fetch_recent(conn, WINDOW_DAYS)
    out: list[DegradingTest] = []
    for test_id, points in grouped.items():
        passed = [(t, d) for t, d, s in points if s == "passed"]
        if len(passed) < MIN_POINTS:
            continue
        t0 = passed[0][0]
        xs = np.array([(t - t0).total_seconds() / 86400.0 for t, _ in passed])
        ys = np.array([d for _, d in passed])
        try:
            res = linregress(xs, ys)
        except Exception:
            continue
        if res.slope >= SLOPE_MS_PER_DAY and res.pvalue <= P_VALUE:
            out.append(DegradingTest(
                test_id=test_id,
                slope_ms_per_day=float(res.slope),
                p_value=float(res.pvalue),
                n_points=len(passed),
                first_ms=float(ys[0]),
                last_ms=float(ys[-1]),
            ))
    out.sort(key=lambda d: d.slope_ms_per_day, reverse=True)
    return out


def detect_slow(conn: sqlite3.Connection) -> list[SlowTest]:
    grouped = _fetch_recent(conn, WINDOW_DAYS)
    if not grouped:
        return []
    medians = {tid: float(np.median([d for _, d, _ in pts])) for tid, pts in grouped.items() if pts}
    if not medians:
        return []
    p95 = float(np.percentile(list(medians.values()), 95))
    out = [
        SlowTest(test_id=tid, median_ms=m, p95_threshold=p95)
        for tid, m in medians.items()
        if m >= p95
    ]
    out.sort(key=lambda s: s.median_ms, reverse=True)
    return out


def detect_flaky(conn: sqlite3.Connection) -> list[FlakyTest]:
    rows = conn.execute(
        """SELECT test_id, status, run_at FROM test_runs
           ORDER BY run_at DESC"""
    ).fetchall()
    by_test: dict[str, list[str]] = {}
    for r in rows:
        statuses = by_test.setdefault(r["test_id"], [])
        if len(statuses) < FLAKY_WINDOW:
            statuses.append(r["status"])
    out: list[FlakyTest] = []
    for tid, statuses in by_test.items():
        if len(statuses) < FLAKY_WINDOW // 2:
            continue
        passed = sum(1 for s in statuses if s == "passed")
        rate = passed / len(statuses)
        if FLAKY_LOW < rate < FLAKY_HIGH:
            out.append(FlakyTest(test_id=tid, pass_rate=rate, n_runs=len(statuses)))
    out.sort(key=lambda f: abs(f.pass_rate - 0.5))
    return out


def health_report(conn: sqlite3.Connection) -> HealthReport:
    return HealthReport(
        degrading=detect_degrading(conn),
        slow=detect_slow(conn),
        flaky=detect_flaky(conn),
    )
