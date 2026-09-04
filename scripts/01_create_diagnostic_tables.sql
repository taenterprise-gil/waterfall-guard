-- waterfall-guard Supabase schema: base tables backing the Phase 2
-- executive reporting views (see 02_create_dashboard_views.sql).
--
-- Both tables store only what deident.py + engine.py already produce: an
-- opaque correlation token_id, waterfall/rule metadata, and an account
-- balance figure. No PHI-bearing column (name, DOB, MRN, address, etc.)
-- is ever written here - the de-identification vault's token -> raw-value
-- mapping never leaves the local Python process (see deident.py).

create extension if not exists pgcrypto;

-- One row per pipeline run (an EpicClient.fetch_claims() -> engine -> LLM
-- cycle), recording how many claims were analyzed regardless of whether a
-- deadlock was found in that run.
create table if not exists pipeline_runs (
    id uuid primary key default gen_random_uuid(),
    run_at timestamptz not null default now(),
    claims_analyzed integer not null default 0,
    deadlocks_found integer not null default 0
);

-- One row per de-identified deadlock finding plus its LLM diagnosis.
-- token_id matches DeadlockFinding.token_id (engine.py) / the token_id
-- DiagnosticLLMClient.diagnose returns - the same opaque HMAC token used
-- throughout the pipeline, never a raw patient identifier.
create table if not exists deadlock_diagnostics (
    id uuid primary key default gen_random_uuid(),
    token_id text not null,
    waterfall_stage text not null,
    deadlock_type text not null,
    root_cause text,
    routing_fix text,
    recommended_owner text,
    dollar_amount_at_risk numeric(12, 2) not null default 0,
    created_at timestamptz not null default now(),
    resolved_at timestamptz
);

create index if not exists idx_deadlock_diagnostics_deadlock_type
    on deadlock_diagnostics (deadlock_type);
create index if not exists idx_deadlock_diagnostics_recommended_owner
    on deadlock_diagnostics (recommended_owner);
create index if not exists idx_deadlock_diagnostics_created_at
    on deadlock_diagnostics (created_at);
