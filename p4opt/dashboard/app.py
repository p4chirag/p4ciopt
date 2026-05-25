"""Streamlit dashboard — 3 pages: Smart Run | Test Health | History."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# Allow `streamlit run app.py -- --project <root>`
def _project_root() -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=str(Path.cwd()))
    args, _ = parser.parse_known_args(sys.argv[1:])
    return Path(args.project)


PROJECT = _project_root()

# Make package importable when run via `streamlit run`
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from p4opt import db as dbmod  # noqa: E402
from p4opt.monitor.degradation import detect_degrading, detect_flaky, detect_slow  # noqa: E402
from p4opt.selector import select_tests  # noqa: E402
from p4opt.selector.mapper import discover_tests  # noqa: E402
from p4opt.vcs import get_adapter  # noqa: E402

st.set_page_config(
    page_title="P4CIOptimizer",
    page_icon="⚡",
    layout="wide",
)

dbmod.init_db(PROJECT)


@st.cache_resource
def _conn():
    # check_same_thread=False because Streamlit reruns each render on a new thread.
    # Dashboard is read-only against the DB, so this is safe.
    return dbmod.connect(PROJECT, check_same_thread=False)


conn = _conn()


# ---------- Sidebar ----------------------------------------------------------
st.sidebar.title("⚡ P4CIOptimizer")
st.sidebar.caption("Test smarter, ship faster.")
page = st.sidebar.radio("Page", ["Smart Run", "Test Health", "History"])
st.sidebar.markdown(f"**Project:** `{PROJECT}`")


# ---------- Page: Smart Run --------------------------------------------------
def page_smart_run():
    st.title("Smart Run")
    st.caption("Pick a code change. See exactly which tests need to run.")

    col1, col2, col3 = st.columns(3)
    vcs = col1.selectbox("VCS", ["git", "p4"], index=0)
    if vcs == "git":
        ref_from = col2.text_input("From ref", value="HEAD~1")
        ref_to = col3.text_input("To ref", value="HEAD")
        changelist = None
    else:
        changelist = col2.text_input("Changelist", value="")
        ref_from = ref_to = None

    threshold = st.slider("Score threshold", 0.0, 1.0, 0.2, 0.05)

    if not st.button("Analyze", type="primary"):
        st.info("Click **Analyze** to detect changed files and selected tests.")
        return

    try:
        adapter = get_adapter(vcs)
        cs = adapter.get_changeset(ref_from=ref_from, ref_to=ref_to,
                                   changelist=changelist or None,
                                   cwd=str(PROJECT))
    except RuntimeError as e:
        st.error(str(e))
        return

    st.subheader(f"Changeset `{cs.id}` — {len(cs.files)} file(s) changed")
    if cs.files:
        st.code("\n".join(cs.files), language="text")
    else:
        st.warning("No changed files detected.")
        return

    scored = select_tests(list(cs.files), PROJECT, conn, threshold=threshold)
    total_tests = len(discover_tests(PROJECT))

    m1, m2, m3 = st.columns(3)
    m1.metric("Total tests in project", total_tests)
    m2.metric("Smart-selected tests", len(scored))
    saved_pct = (1 - len(scored) / total_tests) * 100 if total_tests else 0
    m3.metric("Tests skipped", f"{saved_pct:.0f}%")

    if scored:
        df = pd.DataFrame([{
            "Test": s.test_id,
            "Score": round(s.score, 3),
            "Why": " | ".join(s.reasons),
        } for s in scored])
        st.dataframe(df, width="stretch", hide_index=True)

        fig = px.bar(
            x=["Full suite", "Smart selection"],
            y=[total_tests, len(scored)],
            labels={"x": "", "y": "Tests"},
            title="Selection vs. full suite",
            color=["Full", "Smart"],
            color_discrete_map={"Full": "#888", "Smart": "#22c55e"},
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.warning("No tests passed the threshold. Try lowering it.")


# ---------- Page: Test Health ------------------------------------------------
def page_test_health():
    st.title("Test Health")
    st.caption("Tests that are degrading, slow, or flaky.")

    degrading = detect_degrading(conn)
    slow = detect_slow(conn)
    flaky = detect_flaky(conn)

    m1, m2, m3 = st.columns(3)
    m1.metric("Degrading", len(degrading), help="Runtime trending up (last 30d, p < 0.05)")
    m2.metric("Slow", len(slow), help="Median above suite p95")
    m3.metric("Flaky", len(flaky), help="Pass-rate between 10–90% over last 20 runs")

    st.subheader("Degrading tests")
    if not degrading:
        st.success("No degrading tests detected.")
    else:
        deg_df = pd.DataFrame([{
            "Test": d.test_id,
            "Slope (ms/day)": round(d.slope_ms_per_day, 1),
            "First (ms)": round(d.first_ms, 0),
            "Last (ms)": round(d.last_ms, 0),
            "p-value": round(d.p_value, 4),
            "N points": d.n_points,
        } for d in degrading])
        st.dataframe(deg_df, width="stretch", hide_index=True)

        # Trend lines for top 3 degrading
        for d in degrading[:3]:
            rows = conn.execute(
                """SELECT run_at, duration_ms FROM test_runs
                   WHERE test_id = ? AND status = 'passed'
                   ORDER BY run_at""",
                (d.test_id,),
            ).fetchall()
            if not rows:
                continue
            tdf = pd.DataFrame([{"run_at": r["run_at"], "ms": r["duration_ms"]} for r in rows])
            tdf["run_at"] = pd.to_datetime(tdf["run_at"])
            fig = px.scatter(
                tdf, x="run_at", y="ms", trendline="ols",
                title=f"{d.test_id}  (+{d.slope_ms_per_day:.1f} ms/day)",
            )
            fig.update_traces(marker={"size": 5})
            st.plotly_chart(fig, width="stretch")

    st.subheader("Slow tests")
    if not slow:
        st.success("No slow tests above suite p95.")
    else:
        slow_df = pd.DataFrame([{
            "Test": s.test_id,
            "Median (ms)": round(s.median_ms, 0),
            "p95 threshold": round(s.p95_threshold, 0),
        } for s in slow])
        st.dataframe(slow_df, width="stretch", hide_index=True)

    st.subheader("Flaky tests")
    if not flaky:
        st.success("No flaky tests detected.")
    else:
        flaky_df = pd.DataFrame([{
            "Test": f.test_id,
            "Pass rate": f"{f.pass_rate * 100:.0f}%",
            "Runs": f.n_runs,
        } for f in flaky])
        st.dataframe(flaky_df, width="stretch", hide_index=True)


# ---------- Page: History ----------------------------------------------------
def page_history():
    st.title("History")
    st.caption("How files and tests have moved together over time.")

    # File ↔ test failure correlation
    rows = conn.execute(
        """SELECT cf.file_path AS file_path, tr.test_id AS test_id,
                  SUM(CASE WHEN tr.status='failed' THEN 1 ELSE 0 END) AS fails,
                  COUNT(DISTINCT tr.changeset_id) AS n
           FROM   change_files cf
           JOIN   test_runs    tr ON tr.changeset_id = cf.changeset_id
           GROUP BY cf.file_path, tr.test_id
           HAVING n >= 3
           ORDER  BY fails DESC"""
    ).fetchall()

    if not rows:
        st.info("No history yet — run `p4opt seed` to populate demo data.")
        return

    df = pd.DataFrame([dict(r) for r in rows])
    df["fail_rate"] = df["fails"] / df["n"]
    top = df[df["fail_rate"] > 0].nlargest(25, "fail_rate")

    st.subheader("File ↔ test failure correlation (top 25)")
    if not top.empty:
        pivot = top.pivot_table(
            index="file_path", columns="test_id", values="fail_rate", fill_value=0
        )
        fig = px.imshow(
            pivot, aspect="auto",
            color_continuous_scale="Reds",
            labels={"color": "fail rate"},
            title="Hot cells = test that often fails when file changes",
        )
        st.plotly_chart(fig, width="stretch")

    st.subheader("Recent runs")
    recent = conn.execute(
        """SELECT run_at, run_group, changeset_id,
                  COUNT(*) AS tests,
                  SUM(duration_ms)/1000.0 AS total_s,
                  SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
           FROM   test_runs
           GROUP  BY run_group
           ORDER  BY run_at DESC
           LIMIT  25"""
    ).fetchall()
    if recent:
        rdf = pd.DataFrame([dict(r) for r in recent])
        st.dataframe(rdf, width="stretch", hide_index=True)


# ---------- Router -----------------------------------------------------------
if page == "Smart Run":
    page_smart_run()
elif page == "Test Health":
    page_test_health()
elif page == "History":
    page_history()
