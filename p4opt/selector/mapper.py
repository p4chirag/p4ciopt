"""Path-based mapping: changed source file -> candidate test files.

Supports both Python (pytest) and Java (JUnit/Maven) layouts:

  Python:
    src/foo.py            ->  tests/test_foo.py     (test_<stem>.py)
    src/foo.py            ->  tests/foo_test.py     (<stem>_test.py)

  Java/Maven:
    src/main/java/.../Foo.java  ->  src/test/java/.../FooTest.java   (<Class>Test)
    src/main/java/.../Foo.java  ->  src/test/java/.../FooIT.java     (integration)
    src/main/java/.../Foo.java  ->  src/test/java/.../TestFoo.java   (Test<Class>)
"""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path


def _is_python_test(name: str) -> bool:
    return name.startswith("test_") and name.endswith(".py") or name.endswith("_test.py")


def _is_java_test(name: str) -> bool:
    if not name.endswith(".java"):
        return False
    stem = name[:-5]  # drop '.java'
    return stem.endswith("Test") or stem.endswith("IT") or stem.startswith("Test")


def discover_tests(project_root: Path) -> list[str]:
    """Find test files (Python + Java) and return paths relative to project_root."""
    project_root = Path(project_root)
    tests: list[str] = []
    seen: set[Path] = set()

    # Python: tests/, test/, project root
    for base_name in ("tests", "test", "."):
        base = project_root if base_name == "." else project_root / base_name
        if not base.exists():
            continue
        for pattern in ("test_*.py", "*_test.py"):
            for p in base.rglob(pattern):
                if p in seen:
                    continue
                seen.add(p)
                tests.append(str(p.relative_to(project_root)).replace("\\", "/"))

    # Java/Maven: src/test/java/**
    java_test_root = project_root / "src" / "test" / "java"
    if java_test_root.exists():
        for p in java_test_root.rglob("*.java"):
            if _is_java_test(p.name) and p not in seen:
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
    return _is_python_test(name) or _is_java_test(name)


def _java_package(path: str) -> str:
    """Return the Java package path (parts after src/{main,test}/java/, no filename).
    Returns '' if path isn't a Maven-layout Java file.
    """
    parts = _normalize(path).split("/")
    for i in range(len(parts) - 1):
        if parts[i] in ("main", "test") and i + 1 < len(parts) and parts[i + 1] == "java":
            return "/".join(parts[i + 2:-1])
    return ""


def _score_pair_python(changed: str, test_file: str) -> tuple[float, str]:
    """Python (pytest) scoring rules."""
    changed_norm = _normalize(changed)
    test_norm = _normalize(test_file)
    cstem = _stem(changed_norm)
    tstem = _stem(test_norm)

    if changed_norm == test_norm:
        return 1.0, "test file changed"
    if _is_python_test(Path(changed_norm).name):
        return 0.0, ""  # test file changed but isn't the one being scored — don't cross-pollute

    expected = f"test_{cstem}"
    if tstem == expected:
        if Path(changed_norm).parent.name in Path(test_norm).parts:
            return 1.0, "exact stem + dir match"
        return 0.95, "exact stem match"

    if tstem == f"{cstem}_test":
        return 0.9, "stem suffix match"

    ratio = SequenceMatcher(None, cstem, tstem.replace("test_", "").replace("_test", "")).ratio()
    if ratio >= 0.75:
        return 0.7 * ratio, f"fuzzy stem ({ratio:.2f})"

    cpkg = Path(changed_norm).parent.name
    if cpkg and cpkg not in ("src", "tests", "test") and cpkg in Path(test_norm).parts:
        return 0.5, f"same package '{cpkg}'"

    return 0.0, ""


def _score_pair_java(changed: str, test_file: str) -> tuple[float, str]:
    """Java (JUnit/Maven) scoring rules."""
    changed_norm = _normalize(changed)
    test_norm = _normalize(test_file)
    cstem = _stem(changed_norm)   # e.g. "PerforceScm"
    tstem = _stem(test_norm)      # e.g. "PerforceScmTest"

    if changed_norm == test_norm:
        return 1.0, "test file changed"
    if _is_java_test(Path(changed_norm).name):
        return 0.0, ""

    same_pkg = _java_package(changed_norm) == _java_package(test_norm) != ""

    # <Class>Test.java for <Class>.java (Maven default)
    if tstem == f"{cstem}Test":
        return (1.0, "exact name + package (Test suffix)") if same_pkg else (0.95, "exact name (Test suffix)")
    # <Class>IT.java (integration test)
    if tstem == f"{cstem}IT":
        return (1.0, "exact name + package (IT suffix)") if same_pkg else (0.9, "exact name (IT suffix)")
    # Test<Class>.java prefix form
    if tstem == f"Test{cstem}":
        return (1.0, "exact name + package (Test prefix)") if same_pkg else (0.95, "exact name (Test prefix)")

    # Fuzzy: compare cstem against the test stem with Test/IT stripped
    test_base = tstem
    for suffix in ("Test", "IT"):
        if test_base.endswith(suffix):
            test_base = test_base[: -len(suffix)]
            break
    if test_base.startswith("Test"):
        test_base = test_base[4:]
    ratio = SequenceMatcher(None, cstem, test_base).ratio()
    if ratio >= 0.75:
        return 0.7 * ratio, f"fuzzy name ({ratio:.2f})"

    if same_pkg:
        return 0.5, "same Java package"
    return 0.0, ""


def _score_pair(changed: str, test_file: str) -> tuple[float, str]:
    """Dispatch to the language-appropriate scorer based on extension."""
    if changed.endswith(".py") and test_file.endswith(".py"):
        return _score_pair_python(changed, test_file)
    if changed.endswith(".java") and test_file.endswith(".java"):
        return _score_pair_java(changed, test_file)
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
