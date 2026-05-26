"""Static import-graph signal: walks Python imports to find transitive
dependents of a changed file.

Why this exists: path-stem matching alone misses cases like
"src/click/utils.py changed → tests/test_commands.py is affected because
commands.py imports utils.py". Historical correlation only learns this after
the failure has happened a few times. The import graph catches it from day 1.

How it works:
  1. Walk every .py file under the project root, ast.parse() it.
  2. Resolve each module's imports (including relative imports) to dotted
     module names.
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
from collections import deque
from pathlib import Path


def _normalize(path: str) -> str:
    return path.replace("\\", "/")


def _path_to_module(path: str) -> tuple[str | None, bool]:
    """Convert a relative file path to (dotted_module_name, is_package).

    Examples:
        src/click/utils.py       -> ("src.click.utils",       False)
        src/click/__init__.py    -> ("src.click",             True)
        tests/test_utils.py      -> ("tests.test_utils",      False)
    """
    p = _normalize(path)
    if not p.endswith(".py"):
        return None, False
    is_pkg = p.endswith("/__init__.py")
    if is_pkg:
        p = p[: -len("/__init__.py")]
    else:
        p = p[:-3]
    mod = p.replace("/", ".")
    return (mod or None, is_pkg)


def _extract_imports(source: str, current_module: str, is_package: bool) -> set[str]:
    """Return the set of dotted module names that `source` imports.

    Resolves relative imports (`from .x import y` / `from ..x import y`)
    based on `current_module` and whether it's a package __init__.py.
    """
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
                # Relative import. For a package __init__.py, `from . import x`
                # resolves to package.x. For a regular module pkg.mod, the same
                # statement resolves to pkg.x (one level up first).
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
                # `from foo.bar import baz` may also be importing the submodule
                # foo.bar.baz — record both possibilities; non-module names
                # (classes / functions) just won't match anything in the graph.
                for alias in node.names:
                    if alias.name and alias.name != "*":
                        out.add(f"{full}.{alias.name}")

    return out


class ImportGraph:
    """Project-wide forward + reverse import graph built once per CLI call."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.path_to_module: dict[str, str] = {}
        self.module_to_path: dict[str, str] = {}
        self.package_modules: set[str] = set()  # modules backed by __init__.py
        self.imports: dict[str, set[str]] = {}    # mod -> verbatim imports
        self.importers: dict[str, set[str]] = {}  # project_mod -> modules that import it
        self._build()

    def _build(self) -> None:
        # First pass: enumerate files, assign module names.
        files: list[tuple[Path, str, str, bool]] = []
        for py in self.project_root.rglob("*.py"):
            try:
                rel = str(py.relative_to(self.project_root)).replace("\\", "/")
            except ValueError:
                continue
            mod, is_pkg = _path_to_module(rel)
            if not mod:
                continue
            self.path_to_module[rel] = mod
            self.module_to_path[mod] = rel
            if is_pkg:
                self.package_modules.add(mod)
            files.append((py, rel, mod, is_pkg))

        # Second pass: parse imports.
        for py, _rel, mod, is_pkg in files:
            try:
                source = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            self.imports[mod] = _extract_imports(source, mod, is_pkg)

        # Build the reverse graph: edge (importing_mod -> project_mod)
        # whenever importing_mod's import set names project_mod.
        project_modules = set(self.path_to_module.values())
        for importing_mod, imported_set in self.imports.items():
            edges: set[str] = set()
            for imported_str in imported_set:
                for project_mod in project_modules:
                    if imported_str == project_mod or project_mod.endswith("." + imported_str):
                        edges.add(project_mod)
            for target in edges:
                if target != importing_mod:
                    self.importers.setdefault(target, set()).add(importing_mod)

    def reachable_modules_from(self, changed_paths: list[str]) -> dict[str, int]:
        """BFS upward from the changed files' modules through reverse imports.

        Returns {module_name: shortest_depth}. Depth 1 = a direct importer of
        a changed module. Depth 2 = imports something that imports a changed
        module. Traversal does NOT expand through __init__.py modules — this
        prevents the re-export false-positive explosion (e.g., every test that
        does `import click` looking connected to every click submodule).

        The seeded changed modules themselves are NOT included in the result.
        """
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
            # Don't expand through package __init__.py — would re-export-explode.
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
    """For each test file path, return (score, reason) from the import graph.

    Returns only entries with score > 0.
    """
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
