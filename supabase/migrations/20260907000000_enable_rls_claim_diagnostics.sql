-- claim_diagnostics was created without RLS, so Supabase's default schema
-- privileges gave the anon/authenticated roles full read/write access to it.
-- This restricts it to read-only for anon/authenticated (used by the
-- Streamlit dashboard); the backend writer uses the service_role key, which
-- bypasses RLS entirely, so this does not affect SupabaseWriter.

alter table public.claim_diagnostics enable row level security;

create policy "Allow read-only access for dashboard"
  on public.claim_diagnostics
  for select
  to anon, authenticated
  using (true);
