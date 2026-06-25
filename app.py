"""Heliene Preventive-Maintenance dashboard (Streamlit entry point).

Run:  streamlit run app.py

Works entirely from a CSV you input — no API or browser automation. Upload a
work-order export in the sidebar (or drop one into data/raw/). The dashboard
classifies active PMs and presents three tabs: All PMs, Maintenance, and
Mechatronics. Each tab shows summary stats (total + late) and the work orders
ordered by due date.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import plotly.express as px
import streamlit as st

# Make `src` importable regardless of where streamlit is launched from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import config as C  # noqa: E402
from src import metrics  # noqa: E402
from src.classify import STREAM_MAINTENANCE, STREAM_MECHATRONICS  # noqa: E402
from src.ingest import RAW_DIR, find_latest_csv  # noqa: E402
from src.pipeline import build_dataset, build_from_csv_bytes  # noqa: E402

STREAM_COLORS = {STREAM_MAINTENANCE: "#1f77b4", STREAM_MECHATRONICS: "#ff7f0e"}

st.set_page_config(page_title="Heliene PM Dashboard", page_icon="🛠️", layout="wide")


@st.cache_data(show_spinner="Processing CSV…")
def _load_upload(name, data):
    return build_from_csv_bytes(name, data)


@st.cache_data(show_spinner="Loading latest export…")
def _load_latest(path, mtime):
    return build_dataset()


def get_dataset(uploaded):
    """Prefer an uploaded CSV; otherwise fall back to the newest file in data/raw/."""
    if uploaded is not None:
        return _load_upload(uploaded.name, uploaded.getvalue())
    path = find_latest_csv()
    if path is None:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    return _load_latest(path, mtime)


def empty_state():
    st.title("🛠️ Heliene PM Dashboard")
    st.info("Upload a work-order CSV to begin.")
    st.markdown(
        """
        **How to get the CSV (manual export):**
        1. Open **Asset Essentials → Work Order → Management** and sign in.
        2. Apply your saved active-work-order view.
        3. Click **More → Export** to download the CSV.
        4. **Upload it in the sidebar** (or drop it into the folder below and reload).
        """
    )
    st.code(RAW_DIR, language="text")


def _due_table(frame, today, include_stream):
    """Build the due-date-ordered display table for a tab."""
    ordered = metrics.by_due_date(frame, today)
    title_col = C.TITLE + "_raw" if (C.TITLE + "_raw") in ordered.columns else C.TITLE
    cols = [C.WORK_ORDER_ID, title_col]
    if include_stream:
        cols.append("pm_stream")
    cols += ["days_until_due", C.DUE_DATE, C.PRIORITY, C.ASSET]
    cols = [c for c in cols if c in ordered.columns]
    return ordered[cols], title_col


def render_tab(frame, today, key_prefix, *, all_view=False, full_df=None, mismatch=None):
    # ---- summary stats ----
    if all_view:
        k = metrics.kpi_summary(full_df, today)
        c = st.columns(6)
        c[0].metric("Total PMs", k["total_pm"])
        c[1].metric("Maintenance", k["maintenance"])
        c[2].metric("Mechatronics", k["mechatronics"])
        c[3].metric("Late (overdue)", k["overdue"])
        c[4].metric("Overdue %", f"{k['overdue_pct']}%")
        c[5].metric("Due ≤7 days", k["due_this_week"])
    else:
        s = metrics.summary_stats(frame, today)
        c = st.columns(4)
        c[0].metric("Total PMs", s["total"])
        c[1].metric("Late (overdue)", s["late"])
        c[2].metric("Overdue %", f"{s['overdue_pct']}%")
        c[3].metric("Due ≤7 days", s["due_this_week"])

    # ---- optional split donut (All tab only) ----
    if all_view:
        sc = metrics.stream_counts(full_df)
        if not sc.empty:
            fig = px.pie(sc, names="pm_stream", values="count", hole=0.5,
                         color="pm_stream", color_discrete_map=STREAM_COLORS)
            fig.update_traces(textinfo="value+percent")
            fig.update_layout(height=260, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, width="stretch")

    # ---- due-date-ordered list ----
    st.markdown("**Work orders — ordered by due date** (overdue first)")
    table, title_col = _due_table(frame, today, include_stream=all_view)
    if table.empty:
        st.info("No PM work orders in this view.")
        return
    st.dataframe(
        table, width="stretch", hide_index=True,
        column_config={
            C.WORK_ORDER_ID: st.column_config.TextColumn("WO #"),
            title_col: st.column_config.TextColumn("Title", width="large"),
            "pm_stream": st.column_config.TextColumn("Stream"),
            "days_until_due": st.column_config.NumberColumn("Days to due (− = late)", format="%d"),
            C.DUE_DATE: st.column_config.DatetimeColumn("Due date", format="YYYY-MM-DD"),
            C.PRIORITY: st.column_config.TextColumn("Priority"),
            C.ASSET: st.column_config.TextColumn("Asset"),
        },
    )
    st.download_button(
        "⬇️ Download this list (CSV)",
        data=table.to_csv(index=False).encode("utf-8"),
        file_name=f"pm_{key_prefix}.csv", mime="text/csv", key=f"dl_{key_prefix}",
    )

    # ---- data-quality note (All tab only) ----
    if all_view and mismatch is not None and not mismatch.empty:
        with st.expander(f"⚠️ Data quality: {len(mismatch)} PM-origin rows whose title didn't classify as PM"):
            st.caption(
                "These have Origin = PM in the CMMS but their title lacks a clean `PM` "
                "token (e.g. a missing space like “MonthlyPM”). They are not counted in "
                "the PM streams and are not auto-reclassified. Fix the source titles."
            )
            cols = [c for c in [C.WORK_ORDER_ID, C.TITLE + "_raw", C.ASSET, C.PRIORITY, C.DUE_DATE]
                    if c in mismatch.columns]
            st.dataframe(mismatch[cols], width="stretch", hide_index=True)


def main():
    st.sidebar.header("Data")
    uploaded = st.sidebar.file_uploader("Upload work-order CSV", type=["csv"])
    as_of = st.sidebar.date_input("As-of date (for late/overdue)", value=date.today())

    ds = get_dataset(uploaded)
    if ds is None:
        empty_state()
        return

    st.title("🛠️ Heliene PM Dashboard")
    src = ds.source_name or "(uploaded file)"
    st.caption(f"Source: `{src}` · {ds.report.get('rows_active', 0)} active work orders · as-of **{as_of:%Y-%m-%d}**")
    st.sidebar.caption(f"Loaded: `{src}`")

    df = ds.df
    pm = df[df["is_pm"]].copy()
    maint = pm[pm["pm_stream"].astype(str) == STREAM_MAINTENANCE].copy()
    mech = pm[pm["pm_stream"].astype(str) == STREAM_MECHATRONICS].copy()

    tab_all, tab_m, tab_e = st.tabs(
        [f"All PMs ({len(pm)})", f"Maintenance ({len(maint)})", f"Mechatronics ({len(mech)})"]
    )
    with tab_all:
        render_tab(pm, as_of, "all", all_view=True, full_df=df, mismatch=ds.mismatch)
    with tab_m:
        render_tab(maint, as_of, "maintenance")
    with tab_e:
        render_tab(mech, as_of, "mechatronics")


if __name__ == "__main__":
    main()
