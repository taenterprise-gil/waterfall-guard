"""
OpenClaw — Healthcare Revenue Recovery Analytics Dashboard
Streamlit application for visualizing orphaned/denied claims diagnostics
pushed from the backend pipeline into a Supabase PostgreSQL table.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from waterfall_guard.integrations.fhir_writeback_client import (
    EpicFHIRWritebackClient,
    ResolutionStatus,
    ResolutionUpdate,
    TenantEpicConfig,
)

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
    ]
    # Unowned/default holding queues (no assigned staff) vs. owned ones —
    # used to synthesize the collision-detection signal below.
    unassigned_wq_pool = ["WQ-204", "WQ-317", "WQ-512"]
    owned_wq_pool = ["WQ-101", "WQ-EDIT-CORRECT", "WQ-450"]
    payers = ["Aetna", "UnitedHealth", "Cigna", "Humana", "Anthem BCBS", "Medicaid", "Medicare"]
    facilities = ["Hancock Regional", "Northgate Clinic", "Riverside Medical", "Summit Health", "Lakeview Care"]

    stage_weights = [0.10, 0.09, 0.08, 0.14, 0.16, 0.15, 0.10, 0.12, 0.06]
    stages = rng.choice(waterfall_stages, size=n, p=stage_weights)
    deadlock_prone_stages = ("Denial Triage", "Appeal Filed", "Adjudication")

    deadlocks = []
    active_hold_names = []
    eligible_wq_ids = []
    unassigned_wq_ids = []
    for s in stages:
        if s in deadlock_prone_stages:
            deadlocks.append(rng.choice(deadlock_pool, p=[0.16, 0.14, 0.12, 0.1, 0.13, 0.1, 0.13, 0.1, 0.02]))
            # Deadlock-prone stages skew toward multiple concurrent holds,
            # which is what makes the collision-detection filter meaningful.
            hold_count = rng.choice([0, 1, 2, 3], p=[0.15, 0.25, 0.35, 0.25])
        else:
            deadlocks.append(rng.choice([None] + deadlock_pool[:4], p=[0.55, 0.15, 0.12, 0.1, 0.08]))
            hold_count = rng.choice([0, 1, 2], p=[0.55, 0.35, 0.10])

        holds = list(rng.choice(hold_pool, size=hold_count, replace=False)) if hold_count else []
        active_hold_names.append(holds)

        wq_count = rng.choice([0, 1, 2], p=[0.4, 0.35, 0.25]) if holds else 0
        wq_choices = list(rng.choice(unassigned_wq_pool + owned_wq_pool, size=wq_count, replace=False)) if wq_count else []
        eligible_wq_ids.append(wq_choices)
        unassigned_wq_ids.append([wq for wq in wq_choices if wq in unassigned_wq_pool])

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
    # Filing deadline is intrinsic to the claim (service date + payer
    # timely-filing window), not tied to when this diagnostic happened to
    # run — so it's generated relative to now, not to created_at. Mostly
    # comfortably in the future, with a realistic minority already overdue
    # or due imminently so the timely-filing alert has something to show.
    now = datetime.now()
    filing_deadline = [now + timedelta(days=int(d)) for d in rng.normal(loc=45, scale=20, size=n)]

    df = pd.DataFrame(
        {
            "token_id": [f"CLM-{100000 + i}" for i in range(n)],
            "waterfall_stage": stages,
            "deadlock_types": deadlocks,
            "active_hold_names": active_hold_names,
            "eligible_wq_ids": eligible_wq_ids,
            "unassigned_wq_ids": unassigned_wq_ids,
            "financial_impact": financial_impact,
            "payer": rng.choice(payers, size=n),
            "facility": rng.choice(facilities, size=n),
            "created_at": created_at,
            "filing_deadline": filing_deadline,
        }
    )
    return df


def load_data():
    client = get_supabase_client()
    if client is not None:
        df = fetch_claims_data(client)
        if not df.empty:
            if "financial_impact" not in df.columns:
                # The de-identified ZDR payload SupabaseWriter persists never
                # includes claim dollar amounts (compliance boundary — see
                # supabase_writer.py), so live rows have no cost data yet.
                df["financial_impact"] = 0.0
            return df, True
    return generate_demo_data(), False


# ----------------------------------------------------------------------------
# Tenant configuration / onboarding gate
# ----------------------------------------------------------------------------
CONFIG_TABLE_NAME = "client_configurations"
INGESTION_MODE_LABELS = {"etl_batch": "ETL Batch", "fhir_api": "FHIR API"}


def get_tenant_id() -> str | None:
    """
    Resolve which client/organization this visitor belongs to, so
    client_configurations is looked up per-tenant instead of hard-coded to
    one deployment-wide default (the bug that made every new client land on
    the already-onboarded "default" tenant and never see the wizard):
      1. ?tenant_id=<org-id> in the URL — the bookmarkable link each client
         gets, e.g. https://.../?tenant_id=summit-health.
      2. A tenant already chosen this browser session (via the picker below,
         or a prior query param), kept in st.session_state across reruns.
    Returns None if neither resolves — the caller then shows the
    organization picker instead of a dashboard/wizard.

    (There's no auth layer yet — client_configurations' RLS policy expects a
    JWT `tenant_id` claim that nothing here issues, so lookups go through
    the service-role client scoped to this table only.)
    """
    query_tenant = st.query_params.get("tenant_id", "").strip()
    if query_tenant:
        st.session_state["tenant_id"] = query_tenant
        return query_tenant

    return st.session_state.get("tenant_id") or None


@st.cache_resource(show_spinner=False)
def get_config_client():
    """
    Service-role Supabase client used only for client_configurations. That
    table's RLS only admits a JWT carrying a tenant_id claim, which this
    single-tenant-per-deployment dashboard never issues, so the service role
    bypasses RLS here instead — scoped to onboarding config, not claim data.
    """
    try:
        from supabase import create_client

        url = st.secrets.get("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
        key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))
        if not url or not key:
            return None
        return create_client(url, key)
    except Exception:
        return None


@st.cache_data(ttl=30, show_spinner=False)
def fetch_client_configuration(_client, tenant_id: str):
    """This tenant's onboarding record, or None if it hasn't been created yet."""
    if _client is None:
        return None
    try:
        response = (
            _client.table(CONFIG_TABLE_NAME)
            .select("*")
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        return response.data
    except Exception as exc:
        st.session_state["config_fetch_error"] = str(exc)
        return None


@st.cache_data(ttl=30, show_spinner=False)
def fetch_known_tenants(_client) -> list[dict]:
    """tenant_id/organization_name pairs already onboarded, for the picker's dropdown."""
    if _client is None:
        return []
    try:
        response = (
            _client.table(CONFIG_TABLE_NAME)
            .select("tenant_id, organization_name")
            .order("organization_name")
            .execute()
        )
        return response.data or []
    except Exception:
        return []


def render_tenant_selector(client) -> None:
    """
    Entry gate shown when no tenant is resolved yet from the URL or this
    browser session. An existing client picks their organization from a
    dropdown; a brand-new client types the Client/Organization ID OpenClaw
    assigned them. Either path lands on the onboarding wizard (if new/
    incomplete) or straight on their dashboard (if already onboarded).
    """
    st.title("Welcome to OpenClaw")
    st.subheader("Select your organization")

    known = fetch_known_tenants(client)
    NEW_OPTION = "+ New client — enter organization ID"
    labels = [f"{t['organization_name']} ({t['tenant_id']})" for t in known]
    label_to_id = dict(zip(labels, [t["tenant_id"] for t in known]))
    options = labels + [NEW_OPTION]

    choice = st.selectbox("Client / Organization", options, index=len(options) - 1)

    if choice == NEW_OPTION:
        new_id = st.text_input(
            "New Client/Organization ID",
            placeholder="e.g. summit-health",
            help="A short slug for this client. It becomes part of their bookmarkable URL.",
        )
        resolved = new_id.strip().lower().replace(" ", "-") or None
    else:
        resolved = label_to_id.get(choice)

    if st.button("Continue", type="primary", disabled=not resolved):
        st.session_state["tenant_id"] = resolved
        st.query_params["tenant_id"] = resolved
        st.rerun()

    st.caption(
        "Tip: bookmark this page with `?tenant_id=your-org-id` in the URL to "
        "skip this screen and go straight to your dashboard next time."
    )


def render_onboarding_wizard(client, tenant_id: str, existing: dict | None):
    """Client Onboarding Wizard: collects config, upserts it as completed."""
    st.title("Welcome to OpenClaw")
    st.subheader("Client Onboarding")
    st.caption(f"Configure this workspace (tenant `{tenant_id}`) to unlock the dashboard.")

    if client is None:
        st.error(
            "SUPABASE_SERVICE_ROLE_KEY is not configured for this deployment — "
            "onboarding can't be saved until it's set."
        )
        return

    existing = existing or {}
    with st.form("onboarding_wizard"):
        organization_name = st.text_input(
            "Hospital / Organization Name", value=existing.get("organization_name", "")
        )
        epic_fhir_base_url = st.text_input(
            "Epic FHIR Base URL", value=existing.get("epic_fhir_base_url", "")
        )
        epic_client_id = st.text_input(
            "Epic OAuth Client ID", value=existing.get("epic_client_id", "")
        )
        mode_keys = list(INGESTION_MODE_LABELS.keys())
        ingestion_mode = st.selectbox(
            "Ingestion Method",
            options=mode_keys,
            format_func=lambda k: INGESTION_MODE_LABELS[k],
            index=mode_keys.index(existing.get("ingestion_mode", "etl_batch")),
        )
        dollar_threshold_default = st.number_input(
            "Default Dollar Impact Threshold ($)",
            min_value=0.0,
            value=float(existing.get("dollar_threshold_default", 500.0)),
            step=50.0,
        )
        submitted = st.form_submit_button("Complete Onboarding")

    if not submitted:
        return
    if not organization_name.strip():
        st.error("Hospital / Organization Name is required.")
        return

    payload = {
        "tenant_id": tenant_id,
        "organization_name": organization_name.strip(),
        "epic_client_id": epic_client_id.strip() or None,
        "epic_fhir_base_url": epic_fhir_base_url.strip() or None,
        "ingestion_mode": ingestion_mode,
        "dollar_threshold_default": dollar_threshold_default,
        "is_onboarding_completed": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        client.table(CONFIG_TABLE_NAME).upsert(payload, on_conflict="tenant_id").execute()
    except Exception as exc:
        st.error(f"Failed to save configuration: {exc}")
        return

    st.cache_data.clear()
    st.success("Onboarding complete — loading your dashboard…")
    st.rerun()


# ----------------------------------------------------------------------------
# Alerts — claim collisions & timely filing risk
# ----------------------------------------------------------------------------
def _as_list(value) -> list:
    """Normalizes a claim's array-ish field (real list, NaN, or None) to a plain list."""
    if isinstance(value, list):
        return value
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    return [value]


def get_filing_deadline_alert_days() -> int:
    """Days-out window for the timely filing alert (claims due within this many days are flagged)."""
    raw = st.secrets.get("FILING_DEADLINE_ALERT_DAYS", os.environ.get("FILING_DEADLINE_ALERT_DAYS", "7"))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 7


def render_alerts(df: pd.DataFrame) -> None:
    """
    Two alert classes surfaced above the detail charts:
      1. Claim collisions — 2+ active edits (hold conditions) on a claim that
         is routing to an unassigned/default holding queue, i.e. multiple
         competing edits with nobody accountable to resolve any of them.
      2. Timely filing risk — claims within `FILING_DEADLINE_ALERT_DAYS` of
         (or past) their real payer filing_deadline.
    """
    active_edit_counts = (
        df["active_hold_names"].apply(lambda v: len(_as_list(v))) if "active_hold_names" in df.columns else pd.Series(0, index=df.index)
    )
    unassigned_counts = (
        df["unassigned_wq_ids"].apply(lambda v: len(_as_list(v))) if "unassigned_wq_ids" in df.columns else pd.Series(0, index=df.index)
    )
    collisions_df = df[(active_edit_counts >= 2) & (unassigned_counts > 0)]

    filing_alert_days = get_filing_deadline_alert_days()
    if "filing_deadline" in df.columns:
        filing_deadline_ts = pd.to_datetime(df["filing_deadline"], errors="coerce", utc=True)
        days_until = (filing_deadline_ts - pd.Timestamp.now(tz="UTC")).dt.total_seconds() / 86400
        filing_mask = filing_deadline_ts.notna() & (days_until <= filing_alert_days)
    else:
        days_until = pd.Series(dtype=float, index=df.index)
        filing_mask = pd.Series(False, index=df.index)

    filing_alerts_df = df[filing_mask].copy()
    if not filing_alerts_df.empty:
        filing_alerts_df["days_until_filing_deadline"] = days_until[filing_mask].round(1).values

    st.markdown("### 🚨 Alerts")

    if not collisions_df.empty:
        st.error(
            f"**Claim collisions:** {len(collisions_df):,} claim(s) have 2+ active edits routing to an "
            f"unassigned/default holding queue — nobody currently owns resolution."
        )
        with st.expander(f"View {len(collisions_df):,} colliding claim(s)"):
            cols = [c for c in ["token_id", "waterfall_stage", "active_hold_names", "unassigned_wq_ids", "financial_impact"] if c in collisions_df.columns]
            st.dataframe(collisions_df[cols], use_container_width=True, height=min(360, 60 + 35 * len(collisions_df)))

    # Timely Filing always renders, even at zero, so staff can see the alert
    # is live and watching rather than wondering whether it ran at all.
    if not filing_alerts_df.empty:
        overdue = filing_alerts_df[filing_alerts_df["days_until_filing_deadline"] < 0]
        upcoming = filing_alerts_df[filing_alerts_df["days_until_filing_deadline"] >= 0]
    else:
        overdue = upcoming = filing_alerts_df

    if not overdue.empty:
        st.error(f"**Timely filing:** {len(overdue):,} claim(s) are PAST their filing deadline.")
    if not upcoming.empty:
        st.warning(f"**Timely filing:** {len(upcoming):,} claim(s) are due within {filing_alert_days} day(s).")
    if filing_alerts_df.empty:
        st.success(f"**Timely filing:** 0 urgent claims — none within {filing_alert_days} day(s) of their filing deadline.")

    st.caption(
        "Filing deadlines for claims ingested before a real payer deadline feed was "
        "wired in are estimated as created_at + 90 days, not a true per-claim deadline."
    )

    if not filing_alerts_df.empty:
        with st.expander(f"View {len(filing_alerts_df):,} claim(s) near/past filing deadline"):
            cols = [c for c in ["token_id", "waterfall_stage", "filing_deadline", "days_until_filing_deadline", "financial_impact"] if c in filing_alerts_df.columns]
            st.dataframe(
                filing_alerts_df[cols].sort_values("days_until_filing_deadline"),
                use_container_width=True,
                height=min(360, 60 + 35 * len(filing_alerts_df)),
            )

    st.markdown("---")


# ----------------------------------------------------------------------------
# Sidebar — filters & connection status
# ----------------------------------------------------------------------------
tenant_id = get_tenant_id()
config_client = get_config_client()

if not tenant_id:
    render_tenant_selector(config_client)
    st.stop()

client_config = fetch_client_configuration(config_client, tenant_id)
onboarded = bool(client_config and client_config.get("is_onboarding_completed"))

with st.sidebar:
    st.image("assets/logo.png", width=48)
    st.markdown("### OpenClaw")
    st.caption("Revenue Recovery Diagnostics")
    st.caption(f"Organization: `{tenant_id}`")
    if st.button("Switch organization", use_container_width=True):
        st.session_state.pop("tenant_id", None)
        try:
            del st.query_params["tenant_id"]
        except KeyError:
            pass
        st.rerun()
    st.markdown("---")

    if not onboarded:
        st.info("Complete onboarding to unlock the dashboard.")
        df_raw, is_live = pd.DataFrame(), False
        selected_stages, selected_payers = [], None
        impact_range = (0.0, 0.0)
        only_deadlocked = False
    else:
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
        if max_impact <= min_impact:
            # No cost data yet (e.g. live rows all default to $0) — slider needs
            # a non-degenerate range even though it has nothing to filter.
            max_impact = min_impact + 1.0
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

if not onboarded:
    render_onboarding_wizard(config_client, tenant_id, client_config)
    st.stop()

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

render_alerts(df)

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
    deadlock_series = df["deadlock_types"].dropna().apply(
        lambda v: ", ".join(v) if isinstance(v, list) else str(v)
    )
    deadlock_series = deadlock_series[deadlock_series != ""]
    deadlock_counts = deadlock_series.value_counts().reset_index()
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
    hold_series = df["active_hold_names"].dropna().apply(
        lambda v: ", ".join(v) if isinstance(v, list) else str(v)
    )
    hold_series = hold_series[hold_series != ""]
    hold_counts = hold_series.value_counts().reset_index()
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

# ----------------------------------------------------------------------------
# Row 5 — Post resolution to Epic
# ----------------------------------------------------------------------------
st.markdown("---")
st.subheader("Post Resolution to Epic")
st.caption(
    "Marks a deadlocked claim resolved in Epic. `token_id` is de-identified "
    "and can't be reversed to a real Epic Task ID from this dashboard — "
    "look the claim up in Epic's worklist to get it."
)

RESOLUTION_LABELS = {
    ResolutionStatus.RESOLVED: "Resolved",
    ResolutionStatus.ESCALATED: "Escalated",
    ResolutionStatus.WONT_FIX: "Won't Fix",
}

with st.form("post_resolution_form"):
    ref_token_id = st.selectbox(
        "Claim (token_id, for reference)",
        options=table_df["token_id"].tolist() if "token_id" in table_df.columns else [],
    )
    epic_task_id = st.text_input("Epic FHIR Task ID")
    resolution_status = st.selectbox(
        "Resolution",
        options=list(RESOLUTION_LABELS.keys()),
        format_func=lambda s: RESOLUTION_LABELS[s],
    )
    resolution_note = st.text_area("Resolution note")
    resolved_by = st.text_input("Your name / staff ID")
    post_submitted = st.form_submit_button("Post Resolution to Epic")

if post_submitted:
    if not epic_task_id.strip() or not resolution_note.strip() or not resolved_by.strip():
        st.error("Epic FHIR Task ID, resolution note, and staff ID are all required.")
    else:
        try:
            epic_config = TenantEpicConfig.from_client_configuration_row(
                client_config,
                client_secret=st.secrets.get("EPIC_CLIENT_SECRET", os.environ.get("EPIC_CLIENT_SECRET", "")),
                token_url=st.secrets.get("EPIC_TOKEN_URL", os.environ.get("EPIC_TOKEN_URL", "")),
            )
        except ValueError as exc:
            st.error(f"Epic isn't configured for this tenant yet: {exc}")
        else:
            writeback_client = EpicFHIRWritebackClient(epic_config)
            result = writeback_client.post_resolution(
                ResolutionUpdate(
                    task_id=epic_task_id.strip(),
                    status=resolution_status,
                    note=resolution_note.strip(),
                    resolved_by=resolved_by.strip(),
                )
            )
            if result.ok:
                st.success(f"Epic Task {result.task_id} updated to '{result.fhir_status}'.")
            else:
                st.error(f"Failed to post resolution to Epic: {result.error}")

st.caption("OpenClaw © 2026 · Diagnostic data sourced from Supabase PostgreSQL pipeline · Data refreshes every 60s when connected live.")
