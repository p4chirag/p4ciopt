# P4CIOptimizer — Hackathon Demo Runbook

Keep this open in a side window during the talk. Six beats, ~6 minutes total.

---

## Pre-talk setup (~5 min before going on stage)

### Terminal #1 (left half of screen) — for `p4opt` commands

```powershell
cd c:\dev\AI\P4CIOptimizer
.\.venv\Scripts\Activate.ps1
$env:PYTHONIOENCODING = "utf-8"

# Reseed sample_project so the Test Health page shows fresh patterns
p4opt seed --project sample_project
```

### Terminal #2 (small, bottom-right) — for the dashboard

```powershell
cd c:\dev\AI\P4CIOptimizer
.\.venv\Scripts\Activate.ps1
$env:PYTHONIOENCODING = "utf-8"

# Start dashboard pointed at sample_project (where the seeded patterns live)
python -m streamlit run p4opt\dashboard\app.py `
  --server.port 8501 --browser.gatherUsageStats false `
  -- --project sample_project
# Leave this running; ignore its output. Tab to it only if it crashes.
```

### Browser tabs (pre-open, in this order, left to right)

1. **Dashboard** → http://localhost:8501  *(start on the **Test Health** page)*
2. **PR with live CI run** → https://github.com/p4chirag/click_demo/pull/1
3. **Workflow log w/ green banner** → https://github.com/p4chirag/click_demo/actions/runs/26435610040
4. **Tool source code** → https://github.com/p4chirag/p4ciopt  *(optional — show during Q&A)*

### Quick smoke test (~2 min before)

```powershell
p4opt select --files src/auth.py --project sample_project --explain
# Should print a table with test_auth.py at the top (~0.90 score)
```

If that prints cleanly, you're ready. If anything errors, the dashboard tab + CI tab + screenshots are your backup.

---

## The 6-minute demo

### Beat 1 — The hook (30s)

> *"Engineering teams ship slower every quarter for the same reason: their test suite grew, but the way they decide which tests to run didn't change. They still run every test on every PR. The other problem nobody catches — tests get slower without anyone noticing."*

> *"P4CIOptimizer fixes both. Test smarter. Ship faster."*

### Beat 2 — Smart selection on Python (90s)

**Switch to Terminal #1.**

```powershell
p4opt select --files src/auth.py --project sample_project --explain
```

**Point at the output:**

> *"I changed one file — `src/auth.py`. Out of 7 test files in this project, the selector picked one: `test_auth.py`, score 0.90. But look at WHY — three signals stacked: a path match (0.95), a historical correlation (0.73, because this test failed 75% of the time historically when auth.py changed), AND an import-graph signal (1.00, because the test directly imports the changed module). Three independent ways of saying 'yes, this is the one.'"*

**Switch to the dashboard tab (Test Health).**

> *"Beyond selection, p4opt also watches tests over time. This is the test-health view of the same project."*

Point at the three baked-in patterns on screen:
- *"This test — `test_database_query` — was 200ms a month ago, 850ms today. Nobody noticed in code review. We flagged it. Slope: +12ms/day, statistically significant."*
- *"This one — `test_cache_invalidation` — passes 70% of the time. Classic flake. We flagged it."*
- *"And on the History page, this heatmap shows that `auth.py` and `test_user_auth` light up together — every time auth.py changes, this specific test breaks. That's the correlation we used in the selection."*

### Beat 3 — Real Java/Maven project, the honesty pitch (90s)

**Switch back to Terminal #1.**

> *"Pure Python is the easy case. Watch it on something real — the Perforce Jenkins plugin. 23 test classes, full Maven suite takes 58 minutes."*

**Run scenario A (the leaf):**

```powershell
p4opt ci --vcs git --project p4_plugin_demo `
  --from "b10b3824a~1" --to "b10b3824a" `
  --dry-run --baseline-s 3500
```

> *"This commit was a code-cleanup in `ReviewNotifier.java` — a utility class. One test class in 23 has an import path to it. Smart subset: 1 test. Saved 55 minutes. **96% off a real CI suite.**"*

**Run scenario B (the foundational one):**

```powershell
p4opt ci --vcs git --project p4_plugin_demo `
  --from "0ea4b93a4~1" --to "0ea4b93a4" `
  --dry-run --baseline-s 3500
```

> *"Now watch — same project, different commit. This one touches `PerforceScm.java`, the plugin's central class. Smart subset: **21 of 23.** Only 9% saved."*

> *"That's not a bug. That's the algorithm being honest. Naive selectors would give you the same dramatic number for both commits — and let real regressions through when the change is central. The 2 tests we skip on this run genuinely have no import path to PerforceScm. The other 21 do. **When you see a green check on a PR from p4opt, it means something.**"*

### Beat 4 — Real GitHub Actions, live CI (60s)

**Switch to browser tab #2 (the PR).**

> *"This isn't slideware. Here's a real PR on a public fork of pallets/click — the famous Click CLI library. Every push triggers our workflow."*

Scroll to the **Checks** tab, click into the workflow run.

**Switch to browser tab #3 (the workflow run banner).**

Read the banner aloud:

```
Full suite:    1657 tests in 8.30s   (passed=1631 failed=1)
Smart subset:  156  tests in 0.55s   (passed=156 failed=0)
Saved 7.7s (93%)
Discovered test files: 21  |  Smart-selected: 5
```

> *"GitHub Actions runner installs p4opt straight from the public repo. Runs against the PR's actual base..head diff. **No mocks. No slides. Real CI.**"*

### Beat 5 — The Perforce angle (15s)

**Back to Terminal #1.**

> *"For teams on Perforce — swap one flag."*

Type but don't run:

```powershell
p4opt ci --vcs p4 --cl 12345 --project . --compare
```

> *"Same tool. `p4 describe` instead of `git diff`. Drop into a Jenkinsfile, done."*

### Beat 6 — Close (15s)

> *"Two pain points, one tool. Smart selection — three signals, no ML, no training required, works on day one. Test-health monitoring — degrading, flaky, and slow tests surfaced automatically. Real CI integration in 25 lines of YAML."*

> *"Test smarter. Ship faster. Thanks."*

---

## Backup plans

| If this breaks | Do this |
|---|---|
| Streamlit dashboard won't render | Open browser tab #3 (workflow log) instead — the CI banner is the headline anyway |
| GitHub Actions tab is slow / 404 | Pre-screenshot the green banner; have it in your slide deck |
| `p4opt seed` errors | Skip Beat 2's dashboard portion; spend more time on the Java scenarios (the import-graph story) |
| Wi-fi drops mid-demo | All Beats 2–3 are 100% local. Skip Beat 4 (CI). The local story still lands. |
| Asked "how does it select?" | Open browser tab #4 → `p4opt/selector/scorer.py` and walk the 3-line formula: `0.4 × path + 0.3 × history + 0.3 × import` |

---

## Q&A ammo

**Judge: "What if my project has no test history yet?"**
→ *"Day-one signal is path matching + import graph — both deterministic. Historical correlation kicks in after 5–10 CI runs. Works on a brand-new repo immediately."*

**Judge: "How is this different from pytest-testmon?"**
→ *"Testmon needs a coverage training run and only does Python. We're language-agnostic (Python + Java in this build, Go and TS are 30 lines each to add), and the runtime-degradation surface is something testmon doesn't do at all."*

**Judge: "What about flaky tests in your selected subset?"**
→ *"Health monitor flags them. Dashboard's Test Health page has a Flaky panel — `test_cache_invalidation` is the live example, 70% pass rate over the last 20 runs."*

**Judge: "What's the false-negative rate?"**
→ *"For path-matching alone: high — we miss transitive coupling. With the import graph: low for direct dependencies, can still miss reflection / dynamic-import cases. History fixes those over time. Stretch goal we didn't ship: coverage-map mode — that gets you to near-zero false negatives but needs a one-time training run."*

---

## Key URLs (in case you lose this file)

- Tool repo: https://github.com/p4chirag/p4ciopt
- Click demo fork: https://github.com/p4chirag/click_demo
- Demo PR: https://github.com/p4chirag/click_demo/pull/1
- Green CI run: https://github.com/p4chirag/click_demo/actions/runs/26435610040
