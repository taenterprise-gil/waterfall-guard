"""End-to-end simulation: raw Epic claim data -> de-identification -> the
Rule-vs-Waterfall Reconciliation Engine -> a deadlock diagnosis payload.

The `RAW_CLAIMS` and `RULES_CONFIG` below stand in for a real Epic Clarity
extract and a hospital's rule configuration until `EpicClient.fetch_claims`
(see `integrations/epic_client.py`) is wired up to a live instance.
"""

import json
from typing import Any, Dict, List

from waterfall_guard.deident import Deidentifier
from waterfall_guard.engine import HospitalRuleSet, ReconciliationEngine

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

# Raw Epic Clarity-style extract: PAT_ENC_CSN_ID, patient demographics,
# account balances, and WQ IDs, exactly as they'd come off the source system.
RAW_CLAIMS: List[Dict[str, Any]] = [
    # (1) No exit condition: held on COB with no WQ able to resolve it.
    {
        "PAT_ENC_CSN_ID": "1002345678",
        "PAT_ID": "P-99183",
        "PAT_NAME": "Doe, Jane",
        "BIRTH_DATE": "1980-04-12",
        "ACCOUNT_BALANCE": 482.13,
        "WATERFALL_STAGE": "follow_up",
        "CURRENT_WQ_ID": "WQ-317",
        "ELIGIBLE_WQ_IDS": ["WQ-317"],
        "HOLD_REASON": "cob_pending",
        "DAYS_IN_STAGE": 9,
    },
    # (2) Ambiguous routing: qualifies for two follow-up WQs, both unowned.
    {
        "PAT_ENC_CSN_ID": "1002345679",
        "PAT_ID": "P-88214",
        "PAT_NAME": "Smith, John",
        "BIRTH_DATE": "1975-11-02",
        "ACCOUNT_BALANCE": 1210.55,
        "WATERFALL_STAGE": "follow_up",
        "CURRENT_WQ_ID": "WQ-204",
        "ELIGIBLE_WQ_IDS": ["WQ-204", "WQ-317"],
        "HOLD_REASON": None,
        "DAYS_IN_STAGE": 4,
    },
    # (3) No escalation owner: stalled well past threshold in a queue with
    #     nobody accountable for escalation.
    {
        "PAT_ENC_CSN_ID": "1002345680",
        "PAT_ID": "P-77031",
        "PAT_NAME": "Nguyen, Trang",
        "BIRTH_DATE": "1990-01-22",
        "ACCOUNT_BALANCE": 305.00,
        "WATERFALL_STAGE": "follow_up",
        "CURRENT_WQ_ID": "WQ-204",
        "ELIGIBLE_WQ_IDS": ["WQ-204"],
        "HOLD_REASON": None,
        "DAYS_IN_STAGE": 21,
    },
    # (4) Healthy claim: held on a fixable edit with a clear, owned WQ path.
    {
        "PAT_ENC_CSN_ID": "1002345681",
        "PAT_ID": "P-66120",
        "PAT_NAME": "Alvarez, Maria",
        "BIRTH_DATE": "1965-06-30",
        "ACCOUNT_BALANCE": 87.40,
        "WATERFALL_STAGE": "claim_edit",
        "CURRENT_WQ_ID": "WQ-EDIT-CORRECT",
        "ELIGIBLE_WQ_IDS": ["WQ-EDIT-CORRECT"],
        "HOLD_REASON": "missing_modifier",
        "DAYS_IN_STAGE": 2,
    },
]


def run_simulation() -> Dict[str, Any]:
    """Run the full pipeline and return the ZDR-safe deadlock diagnosis payload."""
    deidentifier = Deidentifier()
    rules = HospitalRuleSet.from_config(RULES_CONFIG)
    engine = ReconciliationEngine(rules)

    deidentified_records = deidentifier.deidentify_batch(RAW_CLAIMS)
    engine_records = [record.as_dict() for record in deidentified_records]

    findings = engine.diagnose_batch(engine_records)
    return engine.build_zdr_payload(findings)


def run() -> None:
    payload = run_simulation()
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    run()
