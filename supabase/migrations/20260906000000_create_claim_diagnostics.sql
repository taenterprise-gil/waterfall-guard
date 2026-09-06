-- De-identified deadlock-diagnostic telemetry written by
-- waterfall_guard.integrations.supabase_writer.SupabaseWriter. Every column
-- here is HMAC token IDs plus waterfall stage/rule metadata produced after
-- deident.py runs - no PHI is ever written to this table.

create table if not exists public.claim_diagnostics (
  id bigint generated always as identity primary key,
  token_id text not null,
  waterfall_stage text not null,
  deadlock_types text[] not null default '{}',
  active_hold_names text[] not null default '{}',
  eligible_wq_ids text[] not null default '{}',
  unassigned_wq_ids text[] not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists claim_diagnostics_token_id_idx
  on public.claim_diagnostics (token_id);
