"""
OpenClaw — Healthcare Revenue Recovery Analytics Dashboard
Streamlit application for visualizing orphaned/denied claims diagnostics
pushed from the backend pipeline into a Supabase PostgreSQL table.
"""

import os
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ----------------------------------------------------------------------------
# Page config
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="OpenClaw — Revenue Recovery Analytics",
    page_icon="assets/logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------------------
# Theme / CSS — Nexus-inspired warm neutral + teal accent, dashboard density
# ----------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --color-bg: #f7f6f2;
    --color-surface: #f9f8f5;
    --color-surface-2: #fbfbf9;
    --color-surface-offset: #f3f0ec;
    --color-border: #d4d1ca;
    --color-text: #28251d;
    --color-text-muted: #7a7974;
    --color-primary: #01696f;
    --color-primary-hover: #0c4e54;
    --color-success: #437a22;
    --color-warning: #964219;
    --color-error: #a12c7b;
    --color-notification: #a13544;
}

html, body, [class*="css"]  {
    font-family: 'Inter', sans-serif;
}

.main {
    background-color: var(--color-bg);
}

[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', monospace;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    color: var(--color-text);
}

[data-testid="stMetricLabel"] {
    color: var(--color-text-muted);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

[data-testid="stMetricDelta"] {
    font-family: 'JetBrains Mono', monospace;
}

div[data-testid="stMetric"] {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 10px;
    padding: 1rem 1.2rem;
}

section[data-testid="stSidebar"] {
    background-color: var(--color-surface-offset);
    border-right: 1px solid var(--color-border);
}

h1, h2, h3 {
    color: var(--color-text);
    font-weight: 700;
}

.stAlert {
    border-radius: 8px;
}

hr {
    border-color: var(--color-border);
}

.status-pill {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.02em;
}
.status-connected {
    background: rgba(67, 122, 34, 0.12);
    color: var(--color-success);
}
.status-demo {
    background: rgba(150, 66, 25, 0.12);
    color: var(--color-warning);
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# Supabase connection
# ----------------------------------------------------------------------------
TABLE_NAME = "claim_diagnostics"
REQUIRED_COLUMNS = [
    "token_id",
    "waterfall_stage",
    "deadlock_types",
    "active_hold_names",
    "financial_impact",
]


@st.cache_resource(show_spinner=False)
def get_supabase_client():
    """
    Initialize the Supabase client using credentials from Streamlit secrets
    or environment variables. Returns None if credentials are unavailable,
    in which case the app falls back to a synthetic demo dataset.
    """
    try:
        from supabase import create_client

        url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
        key = st.secrets.get("SUPABASE_KEY", os.environ.get("SUPABASE_KEY", ""))
        if not url or not key:
            return None
        return create_client(url, key)
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_claims_data(_client, row_limit: int = 5000) -> pd.DataFrame:
    """Pull diagnostic rows from the Supabase table."""
    if _client is None:
        return pd.DataFrame()
    try:
        response = (
            _client.table(TABLE_NAME)
            .select("*")
            .order("created_at", desc=True)
            .limit(row_limit)
            .execute()
        )
        df = pd.DataFrame(response.data)
        if not df.empty and "financial_impact" in df.columns:
            df["financial_impact"] = pd.to_numeric(df["financial_impact"], errors="coerce").fillna(0.0)
        return df
    except Exception as exc:
        st.session_state["fetch_error"] = str(exc)
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def generate_demo_data(n: int = 1200, seed: int = 7) -> pd.DataFrame:
    """
    Synthetic diagnostic dataset matching the OpenClaw schema, used only
    when no live Supabase credentials are configured (demo/dev mode).
    """
    rng = np.random.default_rng(seed)

    waterfall_stages = [
        "Ingestion",
        "Eligibility Check",
        "Coding Validation",
        "Payer Submission",
        "Adjudication",
        "Denial Triage",
        "Appeal Filed",
        "Recovered",
        "Written Off",
    ]
    deadlock_pool = [
        "Missing Prior Auth",
        "Timely Filing Lapse",
        "Duplicate Claim Hold",
        "Coordination of Benefits",
        "Coding Mismatch",
        "Payer System Timeout",
        "Manual Review Queue",
        "Credentialing Gap",
        None,
    ]
    hold_pool = [
        "Payer Portal Sync",
        "COB Verification",
        "Clinical Documentation",
        "Auth Renewal",
        "Legal Review",
        "Provider Follow-up",
        None,
    ]
    payers = ["Aetna", "UnitedHealth", "Cigna", "Humana", "Anthem BCBS", "Medicaid", "Medicare"]
    facilities = ["Hancock Regional", "Northgate Clinic", "Riverside Medical", "Summit Health", "Lakeview Care"]

    stage_weights = [0.10, 0.09, 0.08, 0.14, 0.16, 0.15, 0.10, 0.12, 0.06]
    stages = rng.choice(waterfall_stages, size=n, p=stage_weights)

    deadlocks = []
    for s in stages:
        if s in ("Denial Triage", "Appeal Filed", "Adjudication"):
            deadlocks.append(rng.choice(deadlock_pool, p=[0.16, 0.14, 0.12, 0.1, 0.13, 0.1, 0.13, 0.1, 0.02]))
        else:
            deadlocks.append(rng.choice([None] + deadlock_pool[:4], p=[0.55, 0.15, 0.12, 0.1, 0.08]))

    holds = [rng.choice(hold_pool) if rng.random() > 0.35 else None for _ in range(n)]

    base_impact = rng.gamma(shape=2.2, scale=850, size=n)
    stage_multiplier = np.array([
        1.0 if s not in ("Denial Triage", "Appeal Filed") else rng.uniform(1.3, 2.4)
        for s in stages
    ])
    financial_impact = np.round(base_impact * stage_multiplier, 2)

    created_at = [
        datetime.now() - timedelta(days=int(d), hours=int(rng.integers(0, 23)))
        for d in rng.exponential(scale=25, size=n)
    ]

    df = pd.DataFrame(
        {
            "token_id": [f"CLM-{100000 + i}" for i in range(n)],
            "waterfall_stage": stages,
            "deadlock_types": deadlocks,
            "active_hold_names": holds,
            "financial_impact": financial_impact,
            "payer": rng.choice(payers, size=n),
            "facility": rng.choice(facilities, size=n),
            "created_at": created_at,
        }
    )
    return df


def load_data():
    client = get_supabase_client()
    if client is not None:
        df = fetch_claims_data(client)
        if not df.empty:
            return df, True
    return generate_demo_data(), False


# ----------------------------------------------------------------------------
# Sidebar — filters & connection status
# ----------------------------------------------------------------------------
with st.sidebar:
    st.image("assets/logo.png", width=48)
    st.markdown("### OpenClaw")
    st.caption("Revenue Recovery Diagnostics")
    st.markdown("---")

    df_raw, is_live = load_data()

    if is_live:
        st.markdown('<span class="status-pill status-connected">● Connected to Supabase</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-pill status-demo">● Demo data mode</span>', unsafe_allow_html=True)
        st.caption("Set SUPABASE_URL / SUPABASE_KEY in secrets to connect live.")

    st.markdown("---")
    st.markdown("#### Filters")

    stages_available = sorted(df_raw["waterfall_stage"].dropna().unique().tolist()) if "waterfall_stage" in df_raw else []
    selected_stages = st.multiselect("Waterfall stage", stages_available, default=stages_available)

    if "payer" in df_raw.columns:
        payers_available = sorted(df_raw["payer"].dropna().unique().tolist())
        selected_payers = st.multiselect("Payer", payers_available, default=payers_available)
    else:
        selected_payers = None

    min_impact = float(df_raw["financial_impact"].min()) if "financial_impact" in df_raw and not df_raw.empty else 0.0
    max_impact = float(df_raw["financial_impact"].max()) if "financial_impact" in df_raw and not df_raw.empty else 1000.0
    impact_range = st.slider(
        "Financial impact ($)",
        min_value=float(np.floor(min_impact)),
        max_value=float(np.ceil(max_impact)),
        value=(float(np.floor(min_impact)), float(np.ceil(max_impact))),
    )

    only_deadlocked = st.checkbox("Only show deadlocked claims", value=False)

    st.markdown("---")
    if st.button("🔄 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ----------------------------------------------------------------------------
# Apply filters
# ----------------------------------------------------------------------------
df = df_raw.copy()
if selected_stages:
    df = df[df["waterfall_stage"].isin(selected_stages)]
if selected_payers is not None and "payer" in df.columns:
    df = df[df["payer"].isin(selected_payers)]
df = df[(df["financial_impact"] >= impact_range[0]) & (df["financial_impact"] <= impact_range[1])]
if only_deadlocked and "deadlock_types" in df.columns:
    df = df[df["deadlock_types"].notna()]

# ----------------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------------
header_col1, header_col2 = st.columns([4, 1])
with header_col1:
    st.title("Claims Recovery Analytics")
    st.caption(
        f"Orphaned & denied claims diagnostics · {len(df):,} of {len(df_raw):,} claims shown · "
        f"Last refreshed {datetime.now().strftime('%b %d, %Y %I:%M %p')}"
    )
with header_col2:
    st.metric("Table", TABLE_NAME)

if df.empty:
    st.warning("No claims match the current filters. Adjust filters in the sidebar.")
    st.stop()

# ----------------------------------------------------------------------------
# KPI row
# ----------------------------------------------------------------------------
total_claims = len(df)
total_impact = df["financial_impact"].sum() if "financial_impact" in df.columns else 0.0
deadlocked_claims = df["deadlock_types"].notna().sum() if "deadlock_types" in df.columns else 0
deadlock_rate = (deadlocked_claims / total_claims * 100) if total_claims else 0
active_holds = df["active_hold_names"].notna().sum() if "active_hold_names" in df.columns else 0
recovered_impact = df.loc[df["waterfall_stage"] == "Recovered", "financial_impact"].sum() if "waterfall_stage" in df.columns else 0
avg_impact = df["financial_impact"].mean() if ("financial_impact" in df.columns and total_claims > 0) else 0.0

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("Total Claims", f"{total_claims:,}")
kpi2.metric("Total Financial Impact", f"${total_impact:,.0f}")
kpi3.metric("Deadlock Rate", f"{deadlock_rate:.1f}%", delta=f"{deadlocked_claims:,} claims", delta_color="inverse")
kpi4.metric("Active Holds", f"{active_holds:,}")
kpi5.metric("Avg. Impact / Claim", f"${avg_impact:,.0f}")

st.markdown("---")

# ----------------------------------------------------------------------------
# Row 1 — Waterfall stage funnel + Financial impact by stage
# ----------------------------------------------------------------------------
COLOR_SEQUENCE = ["#01696f", "#0c4e54", "#964219", "#a12c7b", "#437a22", "#d19900", "#7a39bb", "#006494", "#a13544"]

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Claims Waterfall Stage")
    stage_order = [
        "Ingestion", "Eligibility Check", "Coding Validation", "Payer Submission",
        "Adjudication", "Denial Triage", "Appeal Filed", "Recovered", "Written Off",
    ]
    stage_counts = df["waterfall_stage"].value_counts()
    ordered_stages = [s for s in stage_order if s in stage_counts.index]
    remaining = [s for s in stage_counts.index if s not in ordered_stages]
    ordered_stages += remaining
    funnel_values = [stage_counts[s] for s in ordered_stages]

    fig_funnel = go.Figure(
        go.Funnel(
            y=ordered_stages,
            x=funnel_values,
            textinfo="value+percent initial",
            marker={"color": COLOR_SEQUENCE[: len(ordered_stages)]},
        )
    )
    fig_funnel.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#28251d"),
    )
    st.plotly_chart(fig_funnel, use_container_width=True)

with col2:
    st.subheader("Financial Impact by Stage")
    impact_by_stage = (
        df.groupby("waterfall_stage")["financial_impact"]
        .sum()
        .reindex(ordered_stages)
        .fillna(0)
        .reset_index()
    )
    fig_impact = px.bar(
        impact_by_stage,
        x="financial_impact",
        y="waterfall_stage",
        orientation="h",
        color="waterfall_stage",
        color_discrete_sequence=COLOR_SEQUENCE,
        labels={"financial_impact": "Financial Impact ($)", "waterfall_stage": ""},
    )
    fig_impact.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        font=dict(family="Inter, sans-serif", color="#28251d"),
        yaxis=dict(categoryorder="array", categoryarray=ordered_stages[::-1]),
    )
    fig_impact.update_traces(texttemplate="$%{x:,.0f}", textposition="outside")
    st.plotly_chart(fig_impact, use_container_width=True)

# ----------------------------------------------------------------------------
# Row 2 — Deadlock type breakdown + Active hold names
# ----------------------------------------------------------------------------
col3, col4 = st.columns([1, 1])

with col3:
    st.subheader("Deadlock Types")
    deadlock_counts = df["deadlock_types"].dropna().value_counts().reset_index()
    deadlock_counts.columns = ["deadlock_type", "count"]
    if deadlock_counts.empty:
        st.info("No deadlocked claims in the current filter selection.")
    else:
        fig_deadlock = px.treemap(
            deadlock_counts,
            path=["deadlock_type"],
            values="count",
            color="count",
            color_continuous_scale=["#cedcd8", "#01696f", "#0f3638"],
        )
        fig_deadlock.update_layout(
            height=380,
            margin=dict(l=4, r=4, t=4, b=4),
            font=dict(family="Inter, sans-serif", color="#28251d"),
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig_deadlock, use_container_width=True)

with col4:
    st.subheader("Active Hold Names")
    hold_counts = df["active_hold_names"].dropna().value_counts().reset_index()
    hold_counts.columns = ["hold_name", "count"]
    if hold_counts.empty:
        st.info("No active holds in the current filter selection.")
    else:
        fig_holds = px.bar(
            hold_counts.sort_values("count"),
            x="count",
            y="hold_name",
            orientation="h",
            color_discrete_sequence=["#964219"],
            labels={"count": "Claims", "hold_name": ""},
        )
        fig_holds.update_layout(
            height=380,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, sans-serif", color="#28251d"),
        )
        st.plotly_chart(fig_holds, use_container_width=True)

# ----------------------------------------------------------------------------
# Row 3 — Financial impact distribution + trend over time
# ----------------------------------------------------------------------------
col5, col6 = st.columns([1, 1])

with col5:
    st.subheader("Financial Impact Distribution")
    fig_hist = px.histogram(
        df,
        x="financial_impact",
        nbins=40,
        color_discrete_sequence=["#01696f"],
        labels={"financial_impact": "Financial Impact ($)"},
    )
    fig_hist.update_layout(
        height=360,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#28251d"),
        bargap=0.05,
    )
    st.plotly_chart(fig_hist, use_container_width=True)

with col6:
    if "created_at" in df.columns:
        st.subheader("Claims Volume Over Time")
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
        daily = df.dropna(subset=["created_at"]).set_index("created_at").resample("D").agg(
            claims=("token_id", "count"), impact=("financial_impact", "sum")
        ).reset_index()
        fig_trend = go.Figure()
        fig_trend.add_trace(
            go.Scatter(
                x=daily["created_at"], y=daily["claims"], name="Claims",
                mode="lines", line=dict(color="#01696f", width=2), fill="tozeroy",
                fillcolor="rgba(1,105,111,0.08)",
            )
        )
        fig_trend.update_layout(
            height=360,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, sans-serif", color="#28251d"),
            yaxis_title="Claims per day",
        )
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.subheader("Payer Breakdown")
        if "payer" in df.columns:
            payer_impact = df.groupby("payer")["financial_impact"].sum().reset_index()
            fig_payer = px.pie(
                payer_impact, names="payer", values="financial_impact",
                color_discrete_sequence=COLOR_SEQUENCE, hole=0.45,
            )
            fig_payer.update_layout(height=360, font=dict(family="Inter, sans-serif"))
            st.plotly_chart(fig_payer, use_container_width=True)

# ----------------------------------------------------------------------------
# Row 4 — Detailed claims table
# ----------------------------------------------------------------------------
st.markdown("---")
st.subheader("Claim-Level Detail")

display_cols = [c for c in ["token_id", "waterfall_stage", "deadlock_types", "active_hold_names", "financial_impact", "payer", "facility", "created_at"] if c in df.columns]
sort_col = st.selectbox("Sort by", display_cols, index=display_cols.index("financial_impact") if "financial_impact" in display_cols else 0)
sort_desc = st.checkbox("Descending", value=True)

table_df = df[display_cols].sort_values(sort_col, ascending=not sort_desc).reset_index(drop=True)

st.dataframe(
    table_df,
    use_container_width=True,
    height=420,
    column_config={
        "financial_impact": st.column_config.NumberColumn("Financial Impact", format="$%.2f"),
        "token_id": st.column_config.TextColumn("Token ID"),
        "waterfall_stage": st.column_config.TextColumn("Waterfall Stage"),
        "deadlock_types": st.column_config.TextColumn("Deadlock Type"),
        "active_hold_names": st.column_config.TextColumn("Active Hold"),
    },
)

csv_bytes = table_df.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇ Export filtered claims as CSV",
    data=csv_bytes,
    file_name=f"openclaw_claims_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
    mime="text/csv",
)

st.caption("OpenClaw © 2026 · Diagnostic data sourced from Supabase PostgreSQL pipeline · Data refreshes every 60s when connected live.")
