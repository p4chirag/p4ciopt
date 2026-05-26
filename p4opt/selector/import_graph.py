"""Static import-graph signal: walks source-file imports to find transitive
dependents of a changed file. Supports Python (via ast.parse) and Java
(via regex on package/import declarations).

Why this exists: path-stem matching alone misses cases like
"src/click/utils.py changed → tests/test_commands.py is affected because
commands.py imports utils.py internally". Historical correlation only learns
this after the failure has happened a few times. The import graph catches
it from day 1.

How it works:
  1. Walk every .py and .java file under the project root, parse it.
  2. Resolve each module's imports (including Python relative imports and
     Java wildcard imports) to dotted fully-qualified module names.
  3. Build a reverse graph: for each project module M, the set of project
     modules that import it.
  4. BFS upward from the changed files' modules through the reverse graph.
     The shortest path length to each test file becomes its score (with
     decay: depth 1 = 1.0, depth 2 = 0.7, depth 3 = 0.4, deeper = 0.2).
  5. Block traversal *through* package __init__.py modules to avoid the
     "every test that does `import click` looks connected to everything"
     re-export explosion.
"""
from __future__ import annotations

import ast
import re
from collections import deque
from pathlib import Path


JAVA_IMPORT_RE = re.compile(
    r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;", re.MULTILINE
)

# Java Maven layout prefixes — strip these so the FQN matches `import` statements.
JAVA_SRC_PREFIXES = ("src/main/java/", "src/test/java/")


def _java_class_is_test(class_name: str) -> bool:
    """True for FooTest / FooIT / TestFoo (matching mapper.py's _is_java_test)."""
    return (
        class_name.endswith("Test")
        or class_name.endswith("IT")
        or class_name.startswith("Test")
    )


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


# ----- Path → module name ---------------------------------------------------

def _py_path_to_module(path: str) -> tuple[str | None, bool]:
    """Python: 'src/click/utils.py' -> ('src.click.utils', is_package=False)."""
    p = _normalize(path)
    is_pkg = p.endswith("/__init__.py")
    if is_pkg:
        p = p[: -len("/__init__.py")]
    else:
        p = p[:-3]
    mod = p.replace("/", ".")
    return (mod or None, is_pkg)


def _java_path_to_module(path: str) -> tuple[str | None, bool]:
    """Java: 'src/main/java/org/jenkinsci/p4/PerforceScm.java'
            -> ('org.jenkinsci.p4.PerforceScm', is_package=False)"""
    p = _normalize(path)
    if not p.endswith(".java"):
        return None, False
    p = p[:-5]
    for prefix in JAVA_SRC_PREFIXES:
        idx = p.find(prefix)
        if idx >= 0:
            p = p[idx + len(prefix):]
            break
    mod = p.replace("/", ".")
    return (mod or None, False)


def _path_to_module(path: str) -> tuple[str | None, bool]:
    p = _normalize(path)
    if p.endswith(".py"):
        return _py_path_to_module(p)
    if p.endswith(".java"):
        return _java_path_to_module(p)
    return None, False


# ----- Source → imports -----------------------------------------------------

def _extract_python_imports(source: str, current_module: str, is_package: bool) -> set[str]:
    """Return module dotted names imported by Python source. Handles relative
    imports per Python semantics: `from . import x` resolves to package.x for
    a package __init__.py, pkg.x for a regular module inside pkg."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    parts = current_module.split(".") if current_module else []
    out: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)

        elif isinstance(node, ast.ImportFrom):
            level = node.level
            mod = node.module or ""

            if level > 0:
                if is_package:
                    pkg_parts = parts[: len(parts) - (level - 1)] if level > 1 else parts
                else:
                    pkg_parts = parts[: len(parts) - level]
                if not pkg_parts:
                    continue
                base = ".".join(pkg_parts)
                full = f"{base}.{mod}" if mod else base
            else:
                full = mod

            if full:
                out.add(full)
                for alias in node.names:
                    if alias.name and alias.name != "*":
                        out.add(f"{full}.{alias.name}")
    return out


def _extract_java_imports(source: str) -> set[str]:
    """Return Java imports verbatim. Wildcard imports keep their `.*` suffix
    so the matcher can prefix-expand them later."""
    return {m.group(1) for m in JAVA_IMPORT_RE.finditer(source)}


# ----- Import → project module matching -------------------------------------

def _matches(imported: str, project_mod: str) -> bool:
    """Does the textual `imported` string refer to `project_mod` in the graph?

    Rules:
      - Exact: `org.x.Y` matches project `org.x.Y`
      - Suffix: `click.utils` matches project `src.click.utils`
        (handles Python projects that mix `src/`-stripped and full path forms)
      - Wildcard prefix: `org.x.*` matches project `org.x.Y`, `org.x.z.W`, ...
    """
    if imported.endswith(".*"):
        prefix = imported[:-2]
        return project_mod == prefix or project_mod.startswith(prefix + ".")
    if imported == project_mod:
        return True
    if project_mod.endswith("." + imported):
        return True
    return False


# ----- The graph ------------------------------------------------------------

class ImportGraph:
    """Project-wide forward + reverse import graph, built once per CLI call.
    Supports Python and Java sources simultaneously (they don't collide
    because Python and Java FQNs use disjoint namespaces in practice)."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.path_to_module: dict[str, str] = {}
        self.module_to_path: dict[str, str] = {}
        self.package_modules: set[str] = set()       # Python __init__.py modules
        self.imports: dict[str, set[str]] = {}        # mod -> verbatim imports
        self.importers: dict[str, set[str]] = {}      # project_mod -> modules that import it
        self._build()

    def _build(self) -> None:
        files: list[tuple[Path, str, str, bool, str]] = []
        for pattern in ("*.py", "*.java"):
            for path in self.project_root.rglob(pattern):
                try:
                    rel = str(path.relative_to(self.project_root)).replace("\\", "/")
                except ValueError:
                    continue
                mod, is_pkg = _path_to_module(rel)
                if not mod:
                    continue
                lang = "py" if rel.endswith(".py") else "java"
                # First registration wins (Python vs Java shouldn't collide
                # in practice, but guard anyway)
                if rel not in self.path_to_module:
                    self.path_to_module[rel] = mod
                    self.module_to_path[mod] = rel
                    if is_pkg:
                        self.package_modules.add(mod)
                    files.append((path, rel, mod, is_pkg, lang))

        for path, _rel, mod, is_pkg, lang in files:
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if lang == "py":
                self.imports[mod] = _extract_python_imports(source, mod, is_pkg)
            else:  # java
                self.imports[mod] = _extract_java_imports(source)

        # Java: classes in the same package can reference each other *without*
        # explicit `import` statements. Synthesize ONLY the edges we know we
        # need: from test classes to same-package source classes (the common
        # "FooTest.java uses Foo.java without importing it" case). Source ->
        # source same-package edges would create a dense web where every
        # class in a package looks connected to every other.
        java_modules_by_pkg: dict[str, set[str]] = {}
        for mod, rel in self.module_to_path.items():
            if rel.endswith(".java"):
                pkg = ".".join(mod.split(".")[:-1])
                if pkg:
                    java_modules_by_pkg.setdefault(pkg, set()).add(mod)
        for siblings in java_modules_by_pkg.values():
            tests = {m for m in siblings if _java_class_is_test(m.split(".")[-1])}
            non_tests = siblings - tests
            for t in tests:
                for src in non_tests:
                    self.imports.setdefault(t, set()).add(src)

        # Reverse graph: edge importing_mod -> project_mod for each match.
        project_modules = set(self.path_to_module.values())
        for importing_mod, imported_set in self.imports.items():
            edges: set[str] = set()
            for imported_str in imported_set:
                # Fast-path exact lookup
                if imported_str in project_modules:
                    edges.add(imported_str)
                    continue
                for project_mod in project_modules:
                    if _matches(imported_str, project_mod):
                        edges.add(project_mod)
            for target in edges:
                if target != importing_mod:
                    self.importers.setdefault(target, set()).add(importing_mod)

    def reachable_modules_from(self, changed_paths: list[str]) -> dict[str, int]:
        """BFS upward from the changed files' modules through reverse imports.
        Returns {module: shortest_depth}. Seed modules are NOT included."""
        seeds: set[str] = set()
        for cp in changed_paths:
            norm = _normalize(cp)
            mod = self.path_to_module.get(norm)
            if not mod:
                mod_only, _ = _path_to_module(norm)
                if mod_only and mod_only in self.module_to_path:
                    mod = mod_only
            if mod:
                seeds.add(mod)

        result: dict[str, int] = {}
        visited: set[str] = set(seeds)
        queue: deque[tuple[str, int]] = deque()
        for s in seeds:
            for importer in self.importers.get(s, set()):
                queue.append((importer, 1))

        while queue:
            mod, depth = queue.popleft()
            if mod in visited:
                continue
            visited.add(mod)
            prev = result.get(mod)
            if prev is None or depth < prev:
                result[mod] = depth
            # Don't expand through Python package __init__.py — would re-export-explode.
            # (Java has no equivalent — wildcard imports go through `_matches`.)
            if mod in self.package_modules:
                continue
            for importer in self.importers.get(mod, set()):
                if importer not in visited:
                    queue.append((importer, depth + 1))

        return result


def _decay(depth: int) -> tuple[float, str]:
    if depth == 1:
        return 1.0, "imports changed module"
    if depth == 2:
        return 0.7, "imports module that imports changed (depth 2)"
    if depth == 3:
        return 0.4, "transitive importer (depth 3)"
    return 0.2, f"transitive importer (depth {depth})"


def import_scores(
    changed_files: list[str],
    all_tests: list[str],
    project_root: Path,
) -> dict[str, tuple[float, str]]:
    """For each test file path, return (score, reason) from the import graph."""
    graph = ImportGraph(project_root)
    reachable = graph.reachable_modules_from(changed_files)

    out: dict[str, tuple[float, str]] = {}
    for test_path in all_tests:
        test_mod = graph.path_to_module.get(_normalize(test_path))
        if not test_mod:
            continue
        depth = reachable.get(test_mod)
        if depth is None:
            continue
        score, reason = _decay(depth)
        out[test_path] = (score, reason)
    return out
