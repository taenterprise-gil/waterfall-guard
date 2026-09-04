"""End-to-end simulation: Epic ingestion -> de-identification -> the
Rule-vs-Waterfall Reconciliation Engine -> an LLM-generated deadlock
diagnosis.

`EpicClient.fetch_claims` (see `integrations/epic_client.py`) currently
returns mock Clarity/Caboodle data standing in for a live Epic sandbox.
`_offline_demo_transport` below stands in for a real ZDR-compliant LLM
call so `python -m waterfall_guard.main` runs end-to-end with no network
access or API credentials; swap in a real transport (see `llm/client.py`)
once the hospital's LLM contract is wired up.
"""

import json
from typing import Any, Dict, List, Optional

from waterfall_guard.deident import Deidentifier
from waterfall_guard.engine import HospitalRuleSet, ReconciliationEngine
from waterfall_guard.integrations.epic_client import EpicClient
from waterfall_guard.integrations.supabase_writer import (
    SupabaseWriteError,
    SupabaseWriter,
    build_diagnostic_rows,
)
from waterfall_guard.llm.client import DiagnosticLLMClient, ZDRConfig

# A hospital's custom rules: hold conditions that can block a claim from
# exiting its stage, and the secondary WQ gates a claim must clear.
RULES_CONFIG: Dict[str, Any] = {
    "hold_conditions": [
        {
            "name": "coordination_of_benefits_pending",
            "stage": "follow_up",
            "trigger_field": "hold_reason",
            "trigger_equals": "cob_pending",
            # No WQ resolves this hold today -> a genuine dead end.
            "resolves_via_wq": None,
        },
        {
            "name": "missing_modifier",
            "stage": "claim_edit",
            "trigger_field": "hold_reason",
            "trigger_equals": "missing_modifier",
            "resolves_via_wq": "WQ-EDIT-CORRECT",
        },
    ],
    "wq_gates": [
        {
            "wq_id": "WQ-EDIT-CORRECT",
            "stage": "claim_edit",
            "owner": "coding_team",
            "escalation_owner": "coding_supervisor",
        },
        {
            "wq_id": "WQ-204",
            "stage": "follow_up",
            "owner": None,
            "escalation_owner": None,
        },
        {
            "wq_id": "WQ-317",
            "stage": "follow_up",
            "owner": None,
            "escalation_owner": "followup_supervisor",
        },
        {
            "wq_id": "WQ-ACCOUNT-REVIEW",
            "stage": "account",
            "owner": "billing_team",
            "escalation_owner": "billing_supervisor",
        },
    ],
}

# Raw Epic Clarity-style extract, sourced via the mock ingestion layer
# (Clarity join + Caboodle drift check + FHIR Task polling).
RAW_CLAIMS: List[Dict[str, Any]] = EpicClient().fetch_claims()

# Canonical example diagnosis for the "coordination_of_benefits_pending"
# hold above: an 835 COB liability posted at the claim level instead of
# the line-item level, failing Loop 2320 AMT*EAF validation on Resolute's
# COB screen. Matches the exact schema `DiagnosticLLMClient` expects back
# from the LLM (token_id, root_cause, routing_fix, recommended_owner), so
# it doubles as a fixture for local testing of that schema.
SAMPLE_COB_DIAGNOSIS: Dict[str, str] = {
    "token_id": "claim_hash_demo_123",
    "root_cause": (
        "Primary payment posted at claim level instead of line-item level, "
        "causing Loop 2320 AMT*EAF validation failure."
    ),
    "routing_fix": "Map primary 835 COB line-item liability to Resolute COB screen Loop 2320.",
    "recommended_owner": "Claim Edit WQ - COB Specialist",
}


def _run_simulation() -> tuple[Dict[str, Any], Dict[str, float]]:
    """Runs ingestion -> de-identification -> the engine once, returning
    both the ZDR-safe deadlock diagnosis payload and a token_id -> account
    balance map.

    Both come from the same `deidentify_batch` call so their token_ids
    line up - `Deidentifier()` seeds a fresh random HMAC key per instance,
    so a second, separate de-identification pass would mint different
    tokens for the same claims and silently break the dollar-amount
    lookup used when persisting to Supabase.
    """
    deidentifier = Deidentifier()
    rules = HospitalRuleSet.from_config(RULES_CONFIG)
    engine = ReconciliationEngine(rules)

    deidentified_records = deidentifier.deidentify_batch(RAW_CLAIMS)
    engine_records = [record.as_dict() for record in deidentified_records]

    findings = engine.diagnose_batch(engine_records)
    payload = engine.build_zdr_payload(findings)

    dollar_amounts_by_token = {
        record["token_id"]: record.get("account_balance") or 0 for record in engine_records
    }
    return payload, dollar_amounts_by_token


def run_simulation() -> Dict[str, Any]:
    """Run ingestion -> de-identification -> the engine and return the
    ZDR-safe deadlock diagnosis payload."""
    payload, _ = _run_simulation()
    return payload


def _offline_demo_transport(prompt: Dict[str, str], zdr_config: ZDRConfig) -> str:
    """Deterministic stand-in for a real LLM call, used only by `run()`.

    Lets the CLI demo run end-to-end without network access or API
    credentials. Production code should construct `DiagnosticLLMClient`
    with a real transport instead of relying on this default.
    """
    payload = json.loads(prompt["user"])
    diagnoses = []

    for finding in payload["findings"]:
        deadlock_types = finding["deadlock_types"]
        if "no_exit_condition" in deadlock_types:
            if "coordination_of_benefits_pending" in finding["active_hold_names"]:
                root_cause = SAMPLE_COB_DIAGNOSIS["root_cause"]
                routing_fix = SAMPLE_COB_DIAGNOSIS["routing_fix"]
                owner = SAMPLE_COB_DIAGNOSIS["recommended_owner"]
            else:
                root_cause = "An active hold has no work queue configured to resolve it."
                routing_fix = "Add a resolving WQ gate for this hold condition, or route to manual review."
                owner = "revenue_cycle_supervisor"
        elif "ambiguous_wq_routing" in deadlock_types:
            wq_list = ", ".join(finding["eligible_wq_ids"]) or "the eligible WQs"
            root_cause = "The claim qualifies for multiple work queues, none of which are owned."
            routing_fix = f"Assign an owner to one of: {wq_list}."
            owner = "wq_admin"
        else:
            root_cause = "The claim is stalled in a work queue with no escalation path defined."
            stuck_wq = finding["unassigned_wq_ids"][0] if finding["unassigned_wq_ids"] else "the current WQ"
            routing_fix = f"Define an escalation owner for {stuck_wq}."
            owner = "followup_supervisor"

        diagnoses.append(
            {
                "token_id": finding["token_id"],
                "root_cause": root_cause,
                "routing_fix": routing_fix,
                "recommended_owner": owner,
            }
        )

    return json.dumps(diagnoses)


def run_diagnostic_pipeline(
    llm_client: Optional[DiagnosticLLMClient] = None,
    supabase_writer: Optional[SupabaseWriter] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Runs the full pipeline: Epic ingestion -> deident -> engine -> LLM
    diagnosis -> Supabase (pipeline_runs/deadlock_diagnostics).

    Persistence never blocks or fails the pipeline: a misconfigured or
    unreachable Supabase project comes back as `persisted=False` plus a
    `persist_error` message, the same fail-soft contract
    `DiagnosticLLMClient` already uses for the LLM call. Pass
    `persist=False` to skip writing to Supabase entirely (e.g. in tests).
    """
    payload, dollar_amounts_by_token = _run_simulation()
    client = llm_client or DiagnosticLLMClient(transport=_offline_demo_transport)
    result = client.diagnose(payload)
    diagnoses = result.parsed if isinstance(result.parsed, list) else []

    persisted = False
    persist_error: Optional[str] = None
    if persist:
        writer = supabase_writer or SupabaseWriter()
        try:
            writer.record_pipeline_run(
                claims_analyzed=len(RAW_CLAIMS),
                deadlocks_found=payload["finding_count"],
            )
            writer.record_diagnoses(build_diagnostic_rows(payload, diagnoses, dollar_amounts_by_token))
            persisted = True
        except SupabaseWriteError as exc:
            persist_error = str(exc)

    return {
        "diagnostic_payload": payload,
        "llm_ok": result.ok,
        "llm_error": result.error,
        "diagnosis": result.parsed,
        "persisted": persisted,
        "persist_error": persist_error,
    }


def run() -> None:
    print(json.dumps(run_diagnostic_pipeline(), indent=2))


if __name__ == "__main__":
    run()
