-- Phase 2 executive reporting views for waterfall-guard.
--
-- Every view here reads only from the de-identified tables created in
-- 01_create_diagnostic_tables.sql (pipeline_runs, deadlock_diagnostics) -
-- no raw Epic/Clarity/Caboodle table is ever referenced, so nothing
-- selected from a vw_* view below can carry PHI. dashboard_router.py is
-- only ever allowed to query these views, never the base tables directly.

-- Global executive summary: how many claims were analyzed overall, how
-- many are currently deadlocked, total dollars at risk across open
-- deadlocks, and the average time-to-resolution for the ones that have
-- since been closed out.
create or replace view vw_executive_metrics as
select
    coalesce((select sum(claims_analyzed) from pipeline_runs), 0)::bigint
        as total_claims_analyzed,
    (select count(*) from deadlock_diagnostics)::bigint
        as total_deadlocked_claims,
    coalesce((select sum(dollar_amount_at_risk) from deadlock_diagnostics), 0)::numeric(14, 2)
        as total_dollars_at_risk,
    (
        select avg(extract(epoch from (resolved_at - created_at)) / 86400.0)
        from deadlock_diagnostics
        where resolved_at is not null
    )::numeric(10, 2) as avg_resolution_days;

-- Dollar impact and claim count grouped by deadlock/rule-collision type
-- (a hospital's own denial/hold taxonomy - e.g. "Status 9200", "Entity
-- 77", "501(r) Hold" - or the engine's native no_exit_condition /
-- ambiguous_wq_routing / no_escalation_owner types; deadlock_type is
-- whatever label the ingesting pipeline wrote to deadlock_diagnostics).
create or replace view vw_deadlock_breakdown as
select
    deadlock_type,
    count(*)::bigint as claim_count,
    coalesce(sum(dollar_amount_at_risk), 0)::numeric(14, 2) as dollars_at_risk
from deadlock_diagnostics
group by deadlock_type
order by dollars_at_risk desc;

-- At-risk revenue grouped by the work queue / role a diagnosis was
-- routed to, so operations can see where dollars are concentrated.
create or replace view vw_workqueue_routing as
select
    recommended_owner,
    count(*)::bigint as claim_count,
    coalesce(sum(dollar_amount_at_risk), 0)::numeric(14, 2) as dollars_at_risk
from deadlock_diagnostics
group by recommended_owner
order by dollars_at_risk desc;
