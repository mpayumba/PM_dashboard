"""Heliene Preventive-Maintenance dashboard (Streamlit entry point).

Run:  streamlit run app.py

Reads the latest CSV that a human exported from Asset Essentials and dropped
into data/raw/ (Mode A). No browser automation required.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

# Make `src` importable regardless of where streamlit is launched from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import config as C  # noqa: E402
from src import history, metrics, shifts  # noqa: E402
from src.classify import STREAM_MAINTENANCE, STREAM_MECHATRONICS  # noqa: E402
from src.ingest import RAW_DIR, find_latest_csv  # noqa: E402
from src.pipeline import build_dataset  # noqa: E402
from src.refresh import do_refresh  # noqa: E402

STREAM_COLORS = {STREAM_MAINTENANCE: "#1f77b4", STREAM_MECHATRONICS: "#ff7f0e"}
APP_DIR = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="Heliene PM Dashboard", page_icon="🛠️", layout="wide")


@st.cache_data(show_spinner="Loading latest export…")
def _load(cache_key):
    """Cached pipeline load. cache_key=(path, mtime) busts the cache on new files."""
    return build_dataset()


def get_dataset():
    path = find_latest_csv()
    if path is None:
        return None
    try:
        mtime = os.path.getmtime(path)  # TOCTOU-safe: file may vanish between glob and stat
    except OSError:
        return None
    st.session_state["loaded_mtime"] = mtime
    return _load((path, mtime))


def _run_fetch_subprocess():
    """Pull a fresh CSV by running scripts/refresh.py --fetch in a subprocess.

    Playwright's sync API must not run inside Streamlit's script thread, so we
    shell out. Returns (returncode, combined_output).
    """
    script = os.path.join(APP_DIR, "scripts", "refresh.py")
    try:
        res = subprocess.run(
            [sys.executable, script, "--fetch"],
            capture_output=True, text=True, timeout=150, cwd=APP_DIR,
        )
        return res.returncode, ((res.stdout or "") + (res.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 1, "Fetch timed out after 150s — fall back to the manual export (Mode A)."


@st.fragment(run_every="60s")
def _autorefresh_watcher():
    """When enabled, reload the app within ~60s of a new export landing in data/raw."""
    if not st.session_state.get("auto_refresh"):
        return
    path = find_latest_csv()
    if not path:
        return
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return
    loaded = st.session_state.get("loaded_mtime")
    if loaded is not None and mtime != loaded:
        st.cache_data.clear()
        st.rerun(scope="app")


def empty_state():
    st.title("🛠️ Heliene PM Dashboard")
    st.warning("No work-order export found in `data/raw/`.")
    st.markdown(
        """
        **To load data (Mode A — manual export):**
        1. Open **Asset Essentials → Work Order → Management** and sign in.
        2. Apply your saved active-work-order view.
        3. Click **More → Export** to download the CSV.
        4. Move the file into this folder:
        """
    )
    st.code(RAW_DIR, language="text")
    st.markdown("Then click **Reload** (top right) or refresh the page.")
    if st.button("🔄 Reload"):
        st.cache_data.clear()
        st.rerun()


def main():
    # Show the result of the last manual update (set just before a rerun) — done
    # BEFORE the empty-state return so a Pull/Re-read result is never dropped.
    last = st.session_state.pop("update_msg", None)
    if last:
        (st.success if last[0] else st.warning)(last[1])

    ds = get_dataset()
    if ds is None:
        empty_state()
        return

    cfg = ds.config
    df = ds.df

    # ---- Header / freshness + manual update -----------------------------
    left, right = st.columns([0.62, 0.38])
    with left:
        st.title("🛠️ Heliene PM Dashboard")
    with right:
        st.caption(f"**Loaded file:** `{ds.source_name}`")
        if ds.source_modified:
            st.caption(f"**File modified:** {ds.source_modified:%Y-%m-%d %H:%M}")
        meta = history.latest_snapshot_meta()
        if meta:
            st.caption(f"**Last snapshot:** {meta[0]} · {history.snapshot_count()} recorded")
        b1, b2 = st.columns(2)
        if b1.button("⬇️ Pull new CSV", width="stretch",
                     help="Fetch a fresh export from Asset Essentials via the saved login session, then update."):
            with st.spinner("Pulling latest export…"):
                rc, out = _run_fetch_subprocess()
            st.cache_data.clear()
            st.session_state["update_msg"] = (rc == 0, out or "Pull finished.")
            st.rerun()
        if b2.button("🔁 Re-read file", width="stretch",
                     help="Re-read the newest CSV already in data/raw/ (use after dropping a file manually)."):
            res = do_refresh(fetch=False)
            st.cache_data.clear()
            st.session_state["update_msg"] = (res.ok, res.message)
            st.rerun()

    # ---- Sidebar filters -------------------------------------------------
    st.sidebar.header("Filters")
    as_of = st.sidebar.date_input("As-of date (for overdue/aging)", value=date.today())

    pm = df[df["is_pm"]].copy()

    stream_opts = [STREAM_MAINTENANCE, STREAM_MECHATRONICS]
    chosen_streams = st.sidebar.multiselect("PM stream", stream_opts, default=stream_opts)

    def opt_filter(label, col):
        if col in pm.columns:
            vals = sorted(v for v in pm[col].astype(str).str.strip().unique() if v and v.lower() != "nan")
            if len(vals) > 1:
                return st.sidebar.multiselect(label, vals, default=vals)
        return None

    chosen_assets = opt_filter("Asset", C.ASSET)
    tech_col = C.ASSIGNED_TO if C.ASSIGNED_TO in pm.columns else None
    chosen_tech = opt_filter("Technician", tech_col) if tech_col else None
    chosen_priority = opt_filter("Priority", C.PRIORITY)

    due_window = st.sidebar.selectbox(
        "Due-date window",
        ["All", "Overdue", "Due ≤7 days", "Due ≤30 days", "No due date"],
    )

    st.sidebar.divider()
    st.session_state["auto_refresh"] = st.sidebar.checkbox(
        "Auto-refresh while open",
        value=st.session_state.get("auto_refresh", False),
        help="Reload automatically within ~60s when a new export lands in data/raw/.",
    )
    _autorefresh_watcher()

    # Apply filters.
    mask = pm["pm_stream"].astype(str).isin(chosen_streams)
    if chosen_assets is not None:
        mask &= pm[C.ASSET].astype(str).str.strip().isin(chosen_assets)
    if chosen_tech is not None:
        mask &= pm[tech_col].astype(str).str.strip().isin(chosen_tech)
    if chosen_priority is not None:
        mask &= pm[C.PRIORITY].astype(str).str.strip().isin(chosen_priority)

    d = metrics.days_until_due(pm, as_of)
    if due_window == "Overdue":
        mask &= d < 0
    elif due_window == "Due ≤7 days":
        mask &= (d >= 0) & (d <= 7)
    elif due_window == "Due ≤30 days":
        mask &= (d >= 0) & (d <= 30)
    elif due_window == "No due date":
        mask &= d.isna()

    fpm = pm[mask].copy()  # filtered PM frame used for all charts/tables

    # ---- KPI row ---------------------------------------------------------
    k = metrics.kpi_summary(df, as_of)  # headline KPIs use the full unfiltered set
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Active PMs", k["total_pm"])
    c2.metric("Maintenance", k["maintenance"])
    c3.metric("Mechatronics", k["mechatronics"])
    c4.metric("Overdue", k["overdue"])
    c5.metric("Overdue %", f"{k['overdue_pct']}%")

    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.metric("Due today", k["due_today"])
    cc2.metric("Due this week (≤7d)", k["due_this_week"])
    cc3.metric("Due this month (≤30d)", k["due_this_month"])
    cc4.metric("Non-PM active rows", k["non_pm"])

    st.caption(f"Showing **{len(fpm)}** of {k['total_pm']} active PM work orders after filters · as-of **{as_of:%Y-%m-%d}**")
    st.divider()

    # ---- Shift completions ----------------------------------------------
    now = datetime.now()
    cur = shifts.current_shift(now)
    sc = history.shift_completion(cur, as_of=now)
    st.subheader(f"Shift completions — {cur.label}")
    if sc.available:
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Completed this shift", sc.completed_total,
                  help="PM work orders that left the active list (completed/closed) since the shift start.")
        s2.metric("• Maintenance", sc.completed_by_stream.get(STREAM_MAINTENANCE, 0))
        s3.metric("• Mechatronics", sc.completed_by_stream.get(STREAM_MECHATRONICS, 0))
        s4.metric("Completion rate", f"{sc.completion_rate}%",
                  help="Completed ÷ (completed + still-active) this shift.")
        st.caption(
            f"Scheduled at shift start: {sc.scheduled_at_start} · still active: {sc.remaining_active} · "
            f"snapshots this shift: {sc.n_snapshots} (baseline {sc.first_ts}, latest {sc.last_ts})"
        )
        if sc.first_ts:
            base = datetime.strptime(sc.first_ts, "%Y-%m-%d %H:%M:%S")
            if (base - cur.start).total_seconds() > 600:  # baseline >10 min late
                st.caption("⚠️ First snapshot landed well after shift start — completions before it aren't counted.")
    else:
        st.info(
            "No snapshots recorded during this shift yet. Completion tracking begins once the scheduled "
            "hourly pulls — or a manual **Pull new CSV** / **Re-read file** — record snapshots this shift."
        )

    recent = shifts.recent_shifts(now, 8)
    comps = history.recent_shift_completions(recent, as_of=now)
    rows = []
    for c in comps:
        if c.available:
            for stream in (STREAM_MAINTENANCE, STREAM_MECHATRONICS):
                rows.append({"shift": c.shift.label, "stream": stream,
                             "count": c.completed_by_stream.get(stream, 0)})
    if rows:
        cdf = pd.DataFrame(rows)
        order = [c.shift.label for c in reversed(comps)]  # oldest -> newest on x-axis
        fig = px.bar(cdf, x="shift", y="count", color="stream", barmode="stack",
                     color_discrete_map=STREAM_COLORS, category_orders={"shift": order})
        fig.update_layout(xaxis_title=None, yaxis_title="PMs completed", legend_title="Stream")
        st.plotly_chart(fig, width="stretch")
    st.divider()

    # ---- Charts ----------------------------------------------------------
    row1c1, row1c2 = st.columns(2)
    with row1c1:
        st.subheader("Maintenance vs Mechatronics")
        sc = metrics.stream_counts(fpm)
        if not sc.empty:
            fig = px.pie(sc, names="pm_stream", values="count", hole=0.5,
                         color="pm_stream", color_discrete_map=STREAM_COLORS)
            fig.update_traces(textinfo="value+percent")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No PM work orders match the current filters.")

    with row1c2:
        st.subheader("Aging by due date")
        ab = metrics.aging_buckets(fpm, as_of)
        if not ab.empty:
            fig = px.bar(ab, x="bucket", y="count", color="pm_stream", barmode="stack",
                         color_discrete_map=STREAM_COLORS, category_orders={"bucket": list(metrics.AGING_ORDER)})
            fig.update_layout(xaxis_title=None, yaxis_title="Work orders", legend_title="Stream")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No PM work orders match the current filters.")

    row2c1, row2c2 = st.columns(2)
    with row2c1:
        st.subheader("Top assets by open PMs")
        by_asset = metrics.count_by(fpm, C.ASSET, top_n=15)
        if not by_asset.empty:
            fig = px.bar(by_asset.sort_values("count"), x="count", y=C.ASSET, orientation="h")
            fig.update_layout(xaxis_title="Open PMs", yaxis_title=None)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No asset data available.")

    with row2c2:
        st.subheader("By technician")
        if tech_col:
            by_tech = metrics.count_by(fpm, tech_col, top_n=15)
            if not by_tech.empty:
                fig = px.bar(by_tech.sort_values("count"), x="count", y=tech_col, orientation="h")
                fig.update_layout(xaxis_title="Open PMs", yaxis_title=None)
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("No PM work orders match the current filters.")
        else:
            st.info(
                "This export has no assigned-technician column. To enable a "
                "per-technician breakdown, add an **Assigned To** column to the "
                "Asset Essentials view before exporting, then set `assigned_to` "
                "in `config/column_mapping.yaml`."
            )
            if C.REQUESTED_BY in fpm.columns:
                rb = metrics.count_by(fpm, C.REQUESTED_BY)
                if len(rb) > 1:
                    st.caption("Meanwhile, breakdown by requester/planner:")
                    st.plotly_chart(
                        px.bar(rb.sort_values("count"), x="count", y=C.REQUESTED_BY, orientation="h"),
                        width="stretch",
                    )
                elif len(rb) == 1:
                    st.caption(f"All PMs were generated by a single planner: **{rb.iloc[0][C.REQUESTED_BY]}**.")

    st.subheader("Active PMs by assigned week")
    trend = metrics.trend_by_week(fpm, as_of)
    if not trend.empty:
        fig = px.bar(trend, x="week", y="count", color="pm_stream", barmode="stack",
                     color_discrete_map=STREAM_COLORS)
        fig.update_layout(xaxis_title=None, yaxis_title="Work orders", legend_title="Stream")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No dated work orders to plot a trend.")

    st.divider()

    # ---- Data-quality panel ---------------------------------------------
    if not ds.mismatch.empty:
        with st.expander(f"⚠️ Data quality: {len(ds.mismatch)} PM-origin rows whose title didn't classify as PM"):
            st.caption(
                "These work orders have Origin = PM in the CMMS but their title does "
                "not contain a clean `PM` token (e.g. a missing space like “MonthlyPM”, "
                "or a title that omits the PM token). They are NOT counted in the PM "
                "streams above and are NOT auto-reclassified, because their "
                "Maintenance-vs-Mechatronics stream can't be recovered from the title. "
                "Fix the source titles in Asset Essentials to include them."
            )
            cols = [c for c in [C.WORK_ORDER_ID, C.TITLE + "_raw", C.ASSET, C.PRIORITY, C.DUE_DATE] if c in ds.mismatch.columns]
            st.dataframe(ds.mismatch[cols], width="stretch", hide_index=True)

    # ---- Detail table + download ----------------------------------------
    st.subheader("Work-order detail")
    fpm = fpm.copy()
    fpm["days_until_due"] = metrics.days_until_due(fpm, as_of)
    title_col = C.TITLE + "_raw" if (C.TITLE + "_raw") in fpm.columns else C.TITLE
    display_cols = [c for c in [
        C.WORK_ORDER_ID, title_col, "pm_stream", C.PRIORITY, C.ASSET,
        C.DUE_DATE, "days_until_due", C.CREATED_DATE, C.REQUESTED_BY,
    ] if c in fpm.columns]
    table = fpm[display_cols].sort_values("days_until_due", na_position="last")
    st.dataframe(table, width="stretch", hide_index=True)

    st.download_button(
        "⬇️ Download filtered view (CSV)",
        data=table.to_csv(index=False).encode("utf-8"),
        file_name="pm_filtered_view.csv",
        mime="text/csv",
    )

    # ---- Diagnostics -----------------------------------------------------
    with st.expander("Pipeline diagnostics"):
        st.json(ds.report)
        missing = [c for c in (C.ASSIGNED_TO, C.LOCATION) if c not in df.columns]
        if missing:
            st.caption(f"Canonical columns not present in this export: {', '.join(missing)}")


if __name__ == "__main__":
    main()
