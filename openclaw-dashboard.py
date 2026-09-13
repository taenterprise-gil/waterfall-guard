import streamlit as st
import streamlit.components.v1 as components

LOGO_URL = (
    "https://uurrjcsvdtprnpfqpver.supabase.co/storage/v1/object/public/"
    "openclaw%20claim%20recovery%20project/logo%20(1).png"
)

# Illustrative placeholder data — mirrors the real `claim_diagnostics` schema
# (token_id / deadlock_types / active_hold_names / financial_impact /
# filing_deadline) from waterfall_guard/engine.py, not a live query.
CLAIM_ROWS = [
    {
        "token_id": "TKN-7F2A91",
        "deadlock_types": "No Exit Condition",
        "active_holds": "Coding Review",
        "payer": "Aetna",
        "financial_impact": 18420.00,
        "filing_deadline": "2026-09-18",
    },
    {
        "token_id": "TKN-3C88D4",
        "deadlock_types": "Ambiguous WQ Routing",
        "active_holds": "Medical Records",
        "payer": "UnitedHealth",
        "financial_impact": 9260.50,
        "filing_deadline": "2026-09-20",
    },
    {
        "token_id": "TKN-9B1E67",
        "deadlock_types": "No Escalation Owner",
        "active_holds": "Auth Pending",
        "payer": "Cigna",
        "financial_impact": 27110.75,
        "filing_deadline": "2026-09-15",
    },
    {
        "token_id": "TKN-5A44F0",
        "deadlock_types": "No Exit Condition, No Escalation Owner",
        "active_holds": "Coding Review, Auth Pending",
        "payer": "Medicaid",
        "financial_impact": 5340.10,
        "filing_deadline": "2026-10-02",
    },
    {
        "token_id": "TKN-1D77C2",
        "deadlock_types": "Ambiguous WQ Routing",
        "active_holds": "Medical Records",
        "payer": "Humana",
        "financial_impact": 14875.25,
        "filing_deadline": "2026-09-22",
    },
]

TOTAL_CLAIMS = 128
TOTAL_IMPACT = sum(row["financial_impact"] for row in CLAIM_ROWS) * (TOTAL_CLAIMS / len(CLAIM_ROWS))
TIMELY_FILING_ALERTS = 6
CLAIM_COLLISIONS = 3

TABLE_ROWS_HTML = "\n".join(
    f"""
    <tr>
      <td class="mono">{row['token_id']}</td>
      <td>{row['deadlock_types']}</td>
      <td>{row['active_holds']}</td>
      <td>{row['payer']}</td>
      <td class="mono num">${row['financial_impact']:,.2f}</td>
      <td class="mono">{row['filing_deadline']}</td>
    </tr>"""
    for row in CLAIM_ROWS
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
    gap: 16px;
    padding: 20px 24px;
    background: #1e293b;
    border-bottom: 1px solid #334155;
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
    <img src="{LOGO_URL}" alt="OpenClaw logo" />
    <div>
      <h1>OpenClaw Dashboard</h1>
      <p>Healthcare Revenue Recovery Analytics</p>
    </div>
  </div>
  <div class="content">
    <div class="stat-grid">
      <div class="stat-card">
        <div class="label">Total Claims Tracked</div>
        <div class="value">{TOTAL_CLAIMS}</div>
      </div>
      <div class="stat-card">
        <div class="label">Total Financial Impact</div>
        <div class="value">${TOTAL_IMPACT:,.0f}</div>
      </div>
      <div class="stat-card">
        <div class="label">Timely Filing Alerts (est.)</div>
        <div class="value">{TIMELY_FILING_ALERTS}</div>
      </div>
      <div class="stat-card">
        <div class="label">Claim Collisions</div>
        <div class="value">{CLAIM_COLLISIONS}</div>
      </div>
    </div>

    <div class="alert warning">
      &#9888; {TIMELY_FILING_ALERTS} claims fall within the timely-filing window (estimate).
    </div>
    <div class="alert error">
      &#9888; {CLAIM_COLLISIONS} claim collisions detected across active hold queues.
    </div>

    <h2>Claim-Level Detail</h2>
    <table>
      <thead>
        <tr>
          <th>Token ID</th>
          <th>Deadlock Type(s)</th>
          <th>Active Hold(s)</th>
          <th>Payer</th>
          <th>Financial Impact</th>
          <th>Filing Deadline</th>
        </tr>
      </thead>
      <tbody>
        {TABLE_ROWS_HTML}
      </tbody>
    </table>

    <p class="footnote">
      Illustrative data shown above — not wired to live Supabase
      <code>claim_diagnostics</code> rows yet.
    </p>
  </div>
</body>
</html>
"""

# Streamlit Gated Entry Point
components.html(HTML_CONTENT, height=1000, scrolling=True)
