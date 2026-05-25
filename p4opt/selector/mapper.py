"""Path-based mapping: changed source file -> candidate test files.

Heuristics (highest score wins, capped at 1.0):
  1. Exact stem match in tests dir:    src/foo.py -> tests/test_foo.py            (1.0)
  2. Suffix match anywhere under tests/: any tests/**/test_foo.py                  (0.9)
  3. Same module name appears in test:   src/foo.py imported/referenced by test   (0.7)  [path-stem fuzzy]
  4. Test file is in same package dir:   src/pkg/foo.py -> tests/pkg/...           (0.5)
  5. Test file itself was changed:                                                 (1.0)
"""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path


def discover_tests(project_root: Path) -> list[str]:
    """Find pytest test files under common locations and return pytest-style ids.

    Returns relative paths like 'tests/test_foo.py'. Real test-node ids (with ::)
    are resolved later by the runner via `pytest --collect-only`.
    """
    project_root = Path(project_root)
    tests: list[str] = []
    candidates = [
        project_root / "tests",
        project_root / "test",
        project_root,
    ]
    seen: set[Path] = set()
    for base in candidates:
        if not base.exists():
            continue
        for p in base.rglob("test_*.py"):
            if p in seen:
                continue
            seen.add(p)
            tests.append(str(p.relative_to(project_root)).replace("\\", "/"))
        for p in base.rglob("*_test.py"):
            if p in seen:
                continue
            seen.add(p)
            tests.append(str(p.relative_to(project_root)).replace("\\", "/"))
    return sorted(set(tests))


def _normalize(path: str) -> str:
    """Normalize a file path to a project-relative posix-style stem.

    Accepts both repo-relative paths ('src/foo.py') and P4 depot paths
    ('//depot/src/foo.py'). Strips leading '//<depot>/'.
    """
    p = path.replace("\\", "/")
    if p.startswith("//"):
        parts = p.split("/", 3)
        p = parts[3] if len(parts) > 3 else p
    return p


def _stem(path: str) -> str:
    return Path(_normalize(path)).stem


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    return name.startswith("test_") or name.endswith("_test.py")


def _score_pair(changed: str, test_file: str) -> tuple[float, str]:
    """Score one (changed_file, test_file) pair. Returns (score, reason)."""
    if not changed.endswith(".py"):
        return 0.0, ""

    changed_norm = _normalize(changed)
    test_norm = _normalize(test_file)
    cstem = _stem(changed_norm)
    tstem = _stem(test_norm)

    # The test file itself changed — definitely run it; do NOT cross-correlate
    # other tests just because they share the tests/ folder.
    if changed_norm == test_norm:
        return 1.0, "test file changed"
    if _is_test_file(changed_norm):
        return 0.0, ""

    # tests/test_<stem>.py and src/<stem>.py
    expected = f"test_{cstem}"
    if tstem == expected:
        # Bonus if dir structure mirrors:
        if Path(changed_norm).parent.name in Path(test_norm).parts:
            return 1.0, "exact stem + dir match"
        return 0.95, "exact stem match"

    # <stem>_test.py form
    if tstem == f"{cstem}_test":
        return 0.9, "stem suffix match"

    # Fuzzy match on stems (handles renames/typos)
    ratio = SequenceMatcher(None, cstem, tstem.replace("test_", "").replace("_test", "")).ratio()
    if ratio >= 0.75:
        return 0.7 * ratio, f"fuzzy stem ({ratio:.2f})"

    # Same package dir: src/pkg/foo.py & tests/pkg/test_anything.py
    cpkg = Path(changed_norm).parent.name
    if cpkg and cpkg not in ("src", "tests", "test") and cpkg in Path(test_norm).parts:
        return 0.5, f"same package '{cpkg}'"

    return 0.0, ""


def path_scores(
    changed_files: list[str],
    all_tests: list[str],
    project_root: Path,  # noqa: ARG001 (reserved for future use)
) -> dict[str, float]:
    """Return {test_file: best_path_score} across all changed files."""
    result: dict[str, float] = {}
    for test_file in all_tests:
        best = 0.0
        for changed in changed_files:
            score, _ = _score_pair(changed, test_file)
            if score > best:
                best = score
        if best > 0:
            result[test_file] = best
    return result


def path_score_reasons(
    changed_files: list[str],
    test_file: str,
) -> list[str]:
    """Human-readable reasons for a test's path score (for --explain)."""
    reasons: list[str] = []
    for changed in changed_files:
        score, reason = _score_pair(changed, test_file)
        if score > 0:
            reasons.append(f"{Path(changed).name}: {reason}")
    return reasons
