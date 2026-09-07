-- Adds the account-balance figure (non-PHI, already de-identified —
-- see deident.py's PHI_FIELDS) that engine.DeadlockFinding now carries
-- as financial_impact, so the Streamlit dashboard's dollar-value
-- charts/KPIs reflect real data instead of a hardcoded 0.0.

alter table public.claim_diagnostics
  add column if not exists financial_impact numeric not null default 0;
