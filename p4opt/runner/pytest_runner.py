"""Wrap pytest with --json-report so we can capture per-test durations."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestOutcome:
    test_id: str
    duration_ms: float
    status: str  # passed | failed | skipped | error


@dataclass
class RunResult:
    outcomes: list[TestOutcome]
    wall_time_s: float
    exit_code: int


def run_pytest(
    project_root: Path,
    test_targets: list[str] | None = None,
    extra_args: list[str] | None = None,
    env_extra: dict[str, str] | None = None,
) -> RunResult:
    """Invoke pytest in `project_root` and return per-test outcomes.

    If test_targets is None, runs the whole suite. Otherwise runs only those.
    `env_extra` is merged into the subprocess environment (e.g. PYTHONPATH).
    """
    import os

    project_root = Path(project_root)
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "pytest_report.json"
        cmd: list[str] = [
            sys.executable, "-m", "pytest",
            "--json-report", f"--json-report-file={report_path}",
            "-q",
        ]
        if extra_args:
            cmd.extend(extra_args)
        if test_targets:
            cmd.extend(test_targets)

        env = os.environ.copy()
        if env_extra:
            for k, v in env_extra.items():
                # Prepend to existing PATH-like vars instead of overwriting
                if k in ("PYTHONPATH", "PATH") and env.get(k):
                    env[k] = f"{v}{os.pathsep}{env[k]}"
                else:
                    env[k] = v

        t0 = time.perf_counter()
        proc = subprocess.run(
            cmd, cwd=project_root, capture_output=True, text=True, env=env,
        )
        wall = time.perf_counter() - t0

        outcomes: list[TestOutcome] = []
        if report_path.exists():
            try:
                data = json.loads(report_path.read_text())
                for t in data.get("tests", []):
                    outcomes.append(TestOutcome(
                        test_id=t["nodeid"],
                        duration_ms=float(t.get("call", {}).get("duration", 0.0)) * 1000.0,
                        status=t.get("outcome", "unknown"),
                    ))
            except (json.JSONDecodeError, KeyError):
                pass

        return RunResult(outcomes=outcomes, wall_time_s=wall, exit_code=proc.returncode)
