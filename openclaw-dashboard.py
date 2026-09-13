import html
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

LOGO_URL = (
    "https://uurrjcsvdtprnpfqpver.supabase.co/storage/v1/object/public/"
    "openclaw%20claim%20recovery%20project/logo%20(1).png"
)

TABLE_NAME = "claim_diagnostics"
MAX_TABLE_ROWS = 25


def _secret(name: str, default: str = "") -> str:
    return st.secrets.get(name, os.environ.get(name, default))


@st.cache_resource(show_spinner=False)
def get_supabase_client():
    """Read-only Supabase client (anon key), same pattern as app.py."""
    try:
        from supabase import create_client

        url = _secret("SUPABASE_URL")
        key = _secret("SUPABASE_KEY")
        if not url or not key:
            return None
        return create_client(url, key)
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_claims_data(_client, row_limit: int = 5000) -> pd.DataFrame:
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
    except Exception:
        return pd.DataFrame()


def _as_list(value) -> list:
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
    try:
        return int(_secret("FILING_DEADLINE_ALERT_DAYS", "7"))
    except (TypeError, ValueError):
        return 7


client = get_supabase_client()
df = fetch_claims_data(client)
is_live = client is not None and not df.empty

# --- Stats -------------------------------------------------------------
total_claims = len(df)
total_impact = float(df["financial_impact"].sum()) if "financial_impact" in df.columns else 0.0

active_edit_counts = (
    df["active_hold_names"].apply(lambda v: len(_as_list(v))) if "active_hold_names" in df.columns else pd.Series(dtype=int)
)
unassigned_counts = (
    df["unassigned_wq_ids"].apply(lambda v: len(_as_list(v))) if "unassigned_wq_ids" in df.columns else pd.Series(dtype=int)
)
if not df.empty and "active_hold_names" in df.columns and "unassigned_wq_ids" in df.columns:
    collisions_df = df[(active_edit_counts >= 2) & (unassigned_counts > 0)]
else:
    collisions_df = df.iloc[0:0]

filing_alert_days = get_filing_deadline_alert_days()
if not df.empty and "filing_deadline" in df.columns:
    filing_deadline_ts = pd.to_datetime(df["filing_deadline"], errors="coerce", utc=True)
    days_until = (filing_deadline_ts - pd.Timestamp.now(tz="UTC")).dt.total_seconds() / 86400
    filing_mask = filing_deadline_ts.notna() & (days_until <= filing_alert_days)
    filing_alerts_df = df[filing_mask]
else:
    filing_alerts_df = df.iloc[0:0]

claim_collisions = len(collisions_df)
timely_filing_alerts = len(filing_alerts_df)

# --- Table rows ----------------------------------------------------------
def _format_deadline(value) -> str:
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    ts = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(ts):
        return "—"
    return ts.strftime("%Y-%m-%d")


table_df = df.sort_values("financial_impact", ascending=False) if "financial_impact" in df.columns else df
table_df = table_df.head(MAX_TABLE_ROWS)

row_html_parts = []
for _, row in table_df.iterrows():
    token_id = html.escape(str(row.get("token_id", "—")))
    deadlock_types = html.escape(", ".join(_as_list(row.get("deadlock_types"))) or "—")
    active_holds = html.escape(", ".join(_as_list(row.get("active_hold_names"))) or "—")
    waterfall_stage = html.escape(str(row.get("waterfall_stage", "—")))
    financial_impact = float(row.get("financial_impact", 0.0) or 0.0)
    filing_deadline = _format_deadline(row.get("filing_deadline"))
    row_html_parts.append(
        f"""
    <tr>
      <td class="mono">{token_id}</td>
      <td>{waterfall_stage}</td>
      <td>{deadlock_types}</td>
      <td>{active_holds}</td>
      <td class="mono num">${financial_impact:,.2f}</td>
      <td class="mono">{filing_deadline}</td>
    </tr>"""
    )

if row_html_parts:
    TABLE_ROWS_HTML = "\n".join(row_html_parts)
else:
    TABLE_ROWS_HTML = """
    <tr><td colspan="6" class="empty">No claim diagnostics rows available.</td></tr>"""

table_note = (
    f"Showing top {len(table_df)} of {total_claims} claims by financial impact."
    if total_claims > len(table_df)
    else f"Showing all {total_claims} claim(s)."
)

status_label = "LIVE" if is_live else "NO DATA"
status_class = "live" if is_live else "offline"
status_note = (
    "Connected to Supabase claim_diagnostics."
    if is_live
    else "No live rows found — check SUPABASE_URL / SUPABASE_KEY secrets and that claim_diagnostics has data."
)

HTML_CONTENT = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  :root {{
    --color-bg: #f7f6f2;
    --color-surface: #ffffff;
    --color-border: #d4d1ca;
    --color-text: #28251d;
    --color-text-muted: #7a7974;
    --color-primary: #01696f;
    --color-warning: #964219;
    --color-error: #a12c7b;
    --color-success: #437a22;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--color-bg);
    color: var(--color-text);
  }}
  .header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 20px 24px;
    background: #1e293b;
    border-bottom: 1px solid #334155;
  }}
  .header-left {{
    display: flex;
    align-items: center;
    gap: 16px;
  }}
  .header img {{
    height: 48px;
    width: auto;
  }}
  .header h1 {{
    font-size: 20px;
    margin: 0;
    color: #e2e8f0;
  }}
  .header p {{
    margin: 2px 0 0;
    font-size: 13px;
    color: #94a3b8;
  }}
  .status-pill {{
    display: inline-block;
    padding: 3px 12px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.04em;
  }}
  .status-pill.live {{
    background: rgba(67, 122, 34, 0.18);
    color: #6fbf3f;
  }}
  .status-pill.offline {{
    background: rgba(150, 66, 25, 0.18);
    color: #d98b52;
  }}
  .content {{
    padding: 24px;
  }}
  .stat-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }}
  .stat-card {{
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    padding: 16px;
  }}
  .stat-card .label {{
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--color-text-muted);
  }}
  .stat-card .value {{
    font-size: 24px;
    font-weight: 600;
    margin-top: 6px;
    font-variant-numeric: tabular-nums;
  }}
  .alert {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 12px;
    font-size: 14px;
  }}
  .alert.warning {{
    background: rgba(150, 66, 25, 0.08);
    border: 1px solid rgba(150, 66, 25, 0.3);
    color: var(--color-warning);
  }}
  .alert.error {{
    background: rgba(161, 44, 123, 0.08);
    border: 1px solid rgba(161, 44, 123, 0.3);
    color: var(--color-error);
  }}
  .alert.success {{
    background: rgba(67, 122, 34, 0.08);
    border: 1px solid rgba(67, 122, 34, 0.3);
    color: var(--color-success);
  }}
  h2 {{
    font-size: 16px;
    margin: 28px 0 12px;
    color: var(--color-text);
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    overflow: hidden;
    font-size: 13px;
  }}
  th, td {{
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid var(--color-border);
  }}
  th {{
    background: #f3f0ec;
    color: var(--color-text-muted);
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.04em;
  }}
  tr:last-child td {{
    border-bottom: none;
  }}
  td.empty {{
    text-align: center;
    color: var(--color-text-muted);
    padding: 24px;
  }}
  .mono {{
    font-family: "JetBrains Mono", ui-monospace, monospace;
  }}
  .num {{
    color: var(--color-primary);
    font-weight: 600;
  }}
  .footnote {{
    margin-top: 16px;
    font-size: 12px;
    color: var(--color-text-muted);
  }}
</style>
</head>
<body>
  <div class="header">
    <div class="header-left">
      <img src="{LOGO_URL}" alt="OpenClaw logo" />
      <div>
        <h1>OpenClaw Dashboard</h1>
        <p>Healthcare Revenue Recovery Analytics</p>
      </div>
    </div>
    <span class="status-pill {status_class}">{status_label}</span>
  </div>
  <div class="content">
    <div class="stat-grid">
      <div class="stat-card">
        <div class="label">Total Claims Tracked</div>
        <div class="value">{total_claims}</div>
      </div>
      <div class="stat-card">
        <div class="label">Total Financial Impact</div>
        <div class="value">${total_impact:,.0f}</div>
      </div>
      <div class="stat-card">
        <div class="label">Timely Filing Alerts</div>
        <div class="value">{timely_filing_alerts}</div>
      </div>
      <div class="stat-card">
        <div class="label">Claim Collisions</div>
        <div class="value">{claim_collisions}</div>
      </div>
    </div>

    <div class="alert {'success' if is_live else 'warning'}">
      {'&#9989;' if is_live else '&#9888;'} {status_note}
    </div>

    <div class="alert warning">
      &#9888; {timely_filing_alerts} claim(s) due within {filing_alert_days} day(s) of their filing deadline (or past it).
    </div>
    <div class="alert error">
      &#9888; {claim_collisions} claim(s) have 2+ active edits routing to an unassigned holding queue.
    </div>

    <h2>Claim-Level Detail</h2>
    <table>
      <thead>
        <tr>
          <th>Token ID</th>
          <th>Stage</th>
          <th>Deadlock Type(s)</th>
          <th>Active Hold(s)</th>
          <th>Financial Impact</th>
          <th>Filing Deadline</th>
        </tr>
      </thead>
      <tbody>
        {TABLE_ROWS_HTML}
      </tbody>
    </table>

    <p class="footnote">{table_note}</p>
  </div>
</body>
</html>
"""

# Streamlit Gated Entry Point
components.html(HTML_CONTENT, height=1000, scrolling=True)
