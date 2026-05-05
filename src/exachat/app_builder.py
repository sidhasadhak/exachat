"""Visual query builder — Streamlit component for the 📊 Build tab.

Field palette on the left, field wells (dimensions/measures/filters/sort)
on the right, and a live query preview below. No drag-and-drop yet —
fields are added via palette buttons and removed via ✕ tags.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import streamlit as st

from exachat.builder import AGGREGATIONS, FILTER_OPS, QueryBuilder, col_type_icon
from exachat.safety import RiskLevel, validate_sql

if TYPE_CHECKING:
    from exachat.core import ExasolChat
    from exachat.metrics import MetricsCatalog


# ── Session state ─────────────────────────────────────────────────────

def _init_builder(first_table: str) -> None:
    if "builder" not in st.session_state:
        st.session_state.builder = _empty_config(first_table)


def _empty_config(table: str) -> dict:
    return {
        "table":        table,
        "dimensions":   [],   # list[str]
        "measures":     [],   # list[{"field","agg","alias"}]
        "metric_names": [],   # list[str]
        "filters":      [],   # list[{"field","op","value"}]
        "sort_field":   "",
        "sort_dir":     "DESC",
        "limit":        500,
    }


# ── Main entry point ──────────────────────────────────────────────────

def render_builder(
    chat: "ExasolChat",
    qb: QueryBuilder,
    metrics_catalog: Optional["MetricsCatalog"] = None,
) -> None:
    from exachat.charts import auto_chart

    tables = qb.table_names()
    if not tables:
        st.info("No tables found in schema.")
        return

    _init_builder(tables[0])
    cfg = st.session_state.builder

    # ── Table selector ────────────────────────────────────────────
    selected_table = st.selectbox(
        "Table",
        tables,
        index=tables.index(cfg["table"]) if cfg["table"] in tables else 0,
        key="b_table",
    )
    if selected_table != cfg["table"]:
        st.session_state.builder = _empty_config(selected_table)
        st.session_state.pop("builder_result", None)
        cfg = st.session_state.builder
        st.rerun()

    cols = qb.columns_for(selected_table)
    col_names = [c.name for c in cols]
    col_map   = {c.name: c for c in cols}
    metrics   = metrics_catalog.all() if metrics_catalog else []

    # ── Two-column layout ─────────────────────────────────────────
    palette_col, wells_col = st.columns([1, 3], gap="large")

    # ── LEFT: Field Palette ───────────────────────────────────────
    with palette_col:
        st.markdown("**📋 Fields**")
        search = st.text_input(
            "search", placeholder="🔍 Search...",
            key="b_search", label_visibility="collapsed",
        )

        active_dims     = set(cfg["dimensions"])
        active_measures = {m["field"] for m in cfg["measures"]}
        active_metrics  = set(cfg["metric_names"])

        for c in cols:
            if search and search.lower() not in c.name.lower():
                continue
            icon = col_type_icon(c.type)
            already_used = c.name in active_dims or c.name in active_measures
            label_color  = "#6b7280" if already_used else "#e8e8e8"

            p1, p2 = st.columns([5, 1])
            with p1:
                st.markdown(
                    f'<div style="line-height:1.3;padding:2px 0">'
                    f'<span style="color:{label_color};font-size:0.83rem">{icon} {c.name}</span><br>'
                    f'<span style="color:#4b5563;font-size:0.7rem">{c.type}</span></div>',
                    unsafe_allow_html=True,
                )
            with p2:
                if st.button("＋", key=f"bp_{c.name}", help=f"Add {c.name}"):
                    _auto_add_field(cfg, c)
                    st.rerun()

        if metrics:
            st.markdown("---")
            st.markdown("**📐 Metrics**")
            for m in metrics:
                already = m["name"] in active_metrics
                p1, p2 = st.columns([5, 1])
                with p1:
                    color = "#6b7280" if already else "#f97316"
                    st.markdown(
                        f'<div style="line-height:1.3;padding:2px 0">'
                        f'<span style="color:{color};font-size:0.83rem">📐 {m["name"]}</span><br>'
                        f'<span style="color:#4b5563;font-size:0.7rem">{m.get("description","")[:38]}</span></div>',
                        unsafe_allow_html=True,
                    )
                with p2:
                    if st.button("＋", key=f"bpm_{m['name']}"):
                        if m["name"] not in cfg["metric_names"]:
                            cfg["metric_names"].append(m["name"])
                        st.rerun()

    # ── RIGHT: Field Wells ────────────────────────────────────────
    with wells_col:

        # DIMENSIONS
        st.markdown(
            "**Dimensions** <span style='color:#6b7280;font-size:0.78rem'>— Group By</span>",
            unsafe_allow_html=True,
        )
        if cfg["dimensions"]:
            tag_cols = st.columns(min(len(cfg["dimensions"]), 5))
            for i, dim in enumerate(cfg["dimensions"]):
                with tag_cols[i % 5]:
                    if st.button(
                        f"✕  {dim}", key=f"rd_{dim}",
                        help="Remove dimension",
                    ):
                        cfg["dimensions"].remove(dim)
                        st.rerun()
        else:
            st.caption("No dimensions — add from the field palette or pick below.")

        new_dim = st.selectbox(
            "add_dim", ["— add dimension —"] + [c for c in col_names if c not in cfg["dimensions"]],
            key="b_new_dim", label_visibility="collapsed",
        )
        if new_dim and new_dim != "— add dimension —":
            cfg["dimensions"].append(new_dim)
            st.rerun()

        st.divider()

        # MEASURES
        st.markdown(
            "**Measures** <span style='color:#6b7280;font-size:0.78rem'>— Aggregated Values</span>",
            unsafe_allow_html=True,
        )
        for i, m in enumerate(cfg["measures"]):
            mc1, mc2, mc3, mc4 = st.columns([3, 2, 3, 1])
            with mc1:
                f_idx = col_names.index(m["field"]) if m["field"] in col_names else 0
                cfg["measures"][i]["field"] = st.selectbox(
                    "Field", col_names, index=f_idx,
                    key=f"mf_{i}", label_visibility="collapsed",
                )
            with mc2:
                a_idx = AGGREGATIONS.index(m["agg"]) if m["agg"] in AGGREGATIONS else 0
                cfg["measures"][i]["agg"] = st.selectbox(
                    "Agg", AGGREGATIONS, index=a_idx,
                    key=f"ma_{i}", label_visibility="collapsed",
                )
            with mc3:
                cfg["measures"][i]["alias"] = st.text_input(
                    "Alias", value=m["alias"],
                    key=f"mal_{i}", label_visibility="collapsed",
                )
            with mc4:
                if st.button("✕", key=f"rm_{i}"):
                    cfg["measures"].pop(i)
                    st.rerun()

        # Active metrics as read-only tags
        for mn in list(cfg["metric_names"]):
            t1, t2 = st.columns([5, 1])
            with t1:
                st.markdown(f'<span style="color:#f97316;font-size:0.82rem">📐 {mn}</span>', unsafe_allow_html=True)
            with t2:
                if st.button("✕", key=f"rmm_{mn}"):
                    cfg["metric_names"].remove(mn)
                    st.rerun()

        if st.button("＋ Add measure", key="b_add_m"):
            num_cols = qb.numeric_columns(selected_table)
            default  = num_cols[0] if num_cols else (col_names[0] if col_names else "")
            cfg["measures"].append({
                "field": default, "agg": "SUM",
                "alias": f"Total {default}",
            })
            st.rerun()

        st.divider()

        # FILTERS
        st.markdown("**Filters**")
        for i, f in enumerate(cfg["filters"]):
            fc1, fc2, fc3, fc4 = st.columns([3, 2, 3, 1])
            with fc1:
                ff_idx = col_names.index(f["field"]) if f["field"] in col_names else 0
                cfg["filters"][i]["field"] = st.selectbox(
                    "Field", col_names, index=ff_idx,
                    key=f"ff_{i}", label_visibility="collapsed",
                )
            with fc2:
                op_idx = FILTER_OPS.index(f["op"]) if f["op"] in FILTER_OPS else 0
                cfg["filters"][i]["op"] = st.selectbox(
                    "Op", FILTER_OPS, index=op_idx,
                    key=f"fo_{i}", label_visibility="collapsed",
                )
            with fc3:
                if f["op"] not in ("IS NULL", "IS NOT NULL"):
                    cfg["filters"][i]["value"] = st.text_input(
                        "Value", value=f.get("value", ""),
                        key=f"fv_{i}", label_visibility="collapsed",
                    )
                else:
                    st.empty()
            with fc4:
                if st.button("✕", key=f"rf_{i}"):
                    cfg["filters"].pop(i)
                    st.rerun()

        if st.button("＋ Add filter", key="b_add_f"):
            cfg["filters"].append({
                "field": col_names[0] if col_names else "",
                "op": "=", "value": "",
            })
            st.rerun()

        st.divider()

        # SORT + LIMIT + RUN
        sort_options = ["—"] + cfg["dimensions"] + [m["alias"] for m in cfg["measures"]] + cfg["metric_names"]
        sc1, sc2, sc3, sc4 = st.columns([3, 2, 2, 2])
        with sc1:
            sf_idx = sort_options.index(cfg["sort_field"]) if cfg["sort_field"] in sort_options else 0
            chosen = st.selectbox("Sort by", sort_options, index=sf_idx, key="b_sort")
            cfg["sort_field"] = "" if chosen == "—" else chosen
        with sc2:
            cfg["sort_dir"] = st.selectbox("Dir", ["DESC", "ASC"], key="b_sort_dir")
        with sc3:
            cfg["limit"] = st.number_input("Limit", value=cfg["limit"], min_value=1, max_value=50000, key="b_limit")
        with sc4:
            st.markdown("<div style='padding-top:1.6rem'></div>", unsafe_allow_html=True)
            run = st.button("▶ Run", type="primary", use_container_width=True, key="b_run")

    # ── Preview ───────────────────────────────────────────────────
    st.divider()

    if run:
        sql = qb.build_sql(cfg, metrics_catalog)
        try:
            verdict = validate_sql(sql)
            if verdict.level == RiskLevel.BLOCKED:
                st.error(f"Blocked: {verdict.reason}")
            else:
                df = chat._db.execute_query(sql, cfg["limit"])
                st.session_state.builder_result = {"sql": sql, "df": df}
        except Exception as e:
            st.error(f"Query failed: {e}")
            st.code(sql, language="sql")
            st.session_state.pop("builder_result", None)

    res = st.session_state.get("builder_result")
    if res:
        with st.expander("🔍 Generated SQL", expanded=False):
            st.code(res["sql"], language="sql")

        df = res["df"]
        if len(df) > 0:
            # Auto-chart
            try:
                dim_names     = cfg["dimensions"]
                measure_names = [m["alias"] for m in cfg["measures"]] + cfg["metric_names"]
                hint = f"Dimensions: {dim_names}, Measures: {measure_names}"
                chart_config = chat.llm.suggest_chart(hint, list(df.columns), len(df))
                chart_obj    = auto_chart(df, chart_config, chat.chart_library)
                if chart_obj:
                    lib, chart = chart_obj
                    if lib == "plotly":
                        st.plotly_chart(chart, use_container_width=True)
                    elif lib == "altair":
                        st.altair_chart(chart, use_container_width=True)
            except Exception:
                pass

            st.dataframe(df, use_container_width=True, height=min(400, 35 * len(df) + 50))

            c_dl, _ = st.columns([1, 5])
            with c_dl:
                st.download_button(
                    "📥 CSV", df.to_csv(index=False),
                    "builder_result.csv", "text/csv",
                    key="b_dl",
                )
        else:
            st.info("Query returned no rows.")


# ── Metrics catalog tab ───────────────────────────────────────────────

def render_metrics_tab(metrics_catalog: Optional["MetricsCatalog"]) -> None:
    """Render the 📐 Metrics tab — browse, add, and remove metrics."""
    if metrics_catalog is None:
        st.info(
            "No metrics catalog loaded. Connect to a database first, "
            "or set **EXACHAT_METRICS_PATH** in your .env file."
        )
        return

    st.markdown(f"### 📐 Metrics Catalog ({metrics_catalog.count} metrics)")

    # ── Existing metrics ──────────────────────────────────────────
    all_metrics = metrics_catalog.all()
    if all_metrics:
        for m in all_metrics:
            with st.expander(f"**{m['name']}** — {m.get('description', '')}", expanded=False):
                st.code(m["sql"], language="sql")
                c1, c2 = st.columns(2)
                with c1:
                    if m.get("dimensions"):
                        st.caption(f"📏 Dimensions: {', '.join(m['dimensions'])}")
                    if m.get("tables"):
                        st.caption(f"🗂 Tables: {', '.join(m['tables'])}")
                with c2:
                    if m.get("filters"):
                        st.caption(f"🔍 Filters: {', '.join(m['filters'])}")
                    if m.get("caveats"):
                        st.caption(f"⚠️ {m['caveats']}")
                if st.button("🗑 Delete", key=f"del_{m['name']}"):
                    metrics_catalog.remove(m["name"])
                    st.success(f"Deleted **{m['name']}**")
                    st.rerun()
    else:
        st.caption("No metrics defined yet. Add one below.")

    st.divider()

    # ── Add new metric ────────────────────────────────────────────
    st.markdown("#### ＋ Add Metric")
    with st.form("add_metric_form"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Name *", placeholder="revenue")
            sql  = st.text_area("SQL Expression *", placeholder='SUM("order_amount") - SUM("refunds")', height=80)
            caveats = st.text_input("Caveats", placeholder="Finance-approved")
        with col2:
            description = st.text_input("Description", placeholder="Total net revenue excluding refunds")
            dimensions  = st.text_input("Valid dimensions (comma-separated)", placeholder="date, country")
            tables      = st.text_input("Source tables (comma-separated)", placeholder="orders, refunds")

        submitted = st.form_submit_button("Save Metric", type="primary")
        if submitted:
            if not name.strip() or not sql.strip():
                st.error("Name and SQL Expression are required.")
            else:
                try:
                    metric = {
                        "name":        name.strip(),
                        "description": description.strip(),
                        "sql":         sql.strip(),
                        "dimensions":  [d.strip() for d in dimensions.split(",") if d.strip()],
                        "tables":      [t.strip() for t in tables.split(",") if t.strip()],
                        "filters":     [],
                        "caveats":     caveats.strip(),
                    }
                    metrics_catalog.add(metric)
                    st.success(f"✅ Metric **{name}** saved!")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))


# ── Helpers ───────────────────────────────────────────────────────────

def _auto_add_field(cfg: dict, col) -> None:
    """Route a palette click to the right well based on column type."""
    from exachat.builder import _is_numeric
    name = col.name
    if _is_numeric(col.type):
        if name not in {m["field"] for m in cfg["measures"]}:
            cfg["measures"].append({
                "field": name,
                "agg":   "SUM",
                "alias": f"Total {name}",
            })
    else:
        if name not in cfg["dimensions"]:
            cfg["dimensions"].append(name)
