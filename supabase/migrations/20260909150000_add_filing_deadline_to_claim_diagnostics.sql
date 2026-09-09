-- Real timely-filing deadline data, so the dashboard's filing-limit alert
-- reflects an actual per-claim deadline instead of approximating off
-- created_at (when the diagnostic ran, not when the claim is due). Nullable:
-- rows written before a hospital's ingestion supplies filing_deadline (or
-- any hospital that doesn't track it) simply have no value here and are
-- excluded from the alert.

alter table public.claim_diagnostics
  add column if not exists filing_deadline timestamptz;
