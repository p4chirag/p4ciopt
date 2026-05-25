# P4CIOptimizer — Test smarter, ship faster.

A hackathon-ready tool that:
1. **Selects only the relevant tests** for a code change (hybrid: path mapping + historical failure correlation).
2. **Detects degrading tests** — silently-slowing, flaky, or chronically slow ones — over time.

Works with **Perforce (P4)** changelists *and* **Git** refs.

---

## Install (zero cost, laptop only)

```powershell
cd c:\dev\AI\P4CIOptimizer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## 60-second demo

```powershell
# 1. Seed 60 days of synthetic history with bake-in demo patterns.
p4opt seed --project sample_project

# 2. Smart-select tests for an `src/auth.py` change.
#    (We don't actually need a git history — the dashboard's Smart Run page
#     also lets you "fake" a change interactively.)
p4opt select --vcs git --project sample_project --from HEAD~1 --to HEAD --explain

# 3. CLI health reports.
p4opt report --section degradation --project sample_project
p4opt report --section flaky       --project sample_project
p4opt report --section slow        --project sample_project

# 4. Launch the dashboard.
p4opt report --project sample_project
# Opens http://localhost:8501  ->  Smart Run | Test Health | History
```

The seeded data is deterministic and contains three obvious patterns:
- `tests/test_database.py::test_database_query` — runtime ramping up over 60 days.
- `tests/test_cache.py::test_cache_invalidation` — flaky (~70% pass rate).
- `tests/test_auth.py::test_user_auth` — fails ~75% of the time when `src/auth.py` is in the changeset.

## P4 mode

```powershell
p4opt select --vcs p4 --cl 12345 --project sample_project --explain
p4opt run    --vcs p4 --cl 12345 --project sample_project
```

The P4 adapter shells out to `p4 describe -s <CL>` (or `p4 opened` for pending work). No P4Python required.

## Architecture

```
CLI (Typer)
  ├── VCS adapter   (Git | P4)
  ├── Selector      (path heuristics + historical correlation)
  ├── Runner        (pytest-json-report)
  ├── Monitor       (linear regression slope, p95, flake rate)
  └── Dashboard     (Streamlit, 3 pages)
                          │
                          ▼
                    SQLite history
```

## Tagline

**Test smarter. Ship faster.**
