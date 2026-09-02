from waterfall_guard.engine import HospitalRuleSet, ReconciliationEngine

RULES_CONFIG = {
    "hold_conditions": [
        {
            "name": "coordination_of_benefits_pending",
            "stage": "follow_up",
            "trigger_field": "hold_reason",
            "trigger_equals": "cob_pending",
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
        {"wq_id": "WQ-204", "stage": "follow_up", "owner": None, "escalation_owner": None},
        {
            "wq_id": "WQ-317",
            "stage": "follow_up",
            "owner": None,
            "escalation_owner": "followup_supervisor",
        },
    ],
}


def make_engine() -> ReconciliationEngine:
    return ReconciliationEngine(HospitalRuleSet.from_config(RULES_CONFIG))


def test_flags_no_exit_condition_for_unresolvable_hold():
    engine = make_engine()
    record = {
        "token_id": "tok_1",
        "waterfall_stage": "follow_up",
        "current_wq_id": "WQ-317",
        "eligible_wq_ids": ["WQ-317"],
        "hold_reason": "cob_pending",
        "days_in_stage": 9,
    }

    finding = engine.diagnose(record)

    assert finding is not None
    assert "no_exit_condition" in finding.deadlock_types
    assert "ambiguous_wq_routing" not in finding.deadlock_types
    assert "no_escalation_owner" not in finding.deadlock_types


def test_flags_ambiguous_wq_routing_when_all_eligible_wqs_unassigned():
    engine = make_engine()
    record = {
        "token_id": "tok_2",
        "waterfall_stage": "follow_up",
        "current_wq_id": "WQ-204",
        "eligible_wq_ids": ["WQ-204", "WQ-317"],
        "hold_reason": None,
        "days_in_stage": 4,
    }

    finding = engine.diagnose(record)

    assert finding is not None
    assert finding.deadlock_types == ["ambiguous_wq_routing"]
    assert set(finding.unassigned_wq_ids) == {"WQ-204", "WQ-317"}


def test_flags_no_escalation_owner_when_stalled_past_threshold():
    engine = make_engine()
    record = {
        "token_id": "tok_3",
        "waterfall_stage": "follow_up",
        "current_wq_id": "WQ-204",
        "eligible_wq_ids": ["WQ-204"],
        "hold_reason": None,
        "days_in_stage": 21,
    }

    finding = engine.diagnose(record)

    assert finding is not None
    assert finding.deadlock_types == ["no_escalation_owner"]


def test_healthy_claim_with_resolvable_hold_is_not_flagged():
    engine = make_engine()
    record = {
        "token_id": "tok_4",
        "waterfall_stage": "claim_edit",
        "current_wq_id": "WQ-EDIT-CORRECT",
        "eligible_wq_ids": ["WQ-EDIT-CORRECT"],
        "hold_reason": "missing_modifier",
        "days_in_stage": 2,
    }

    assert engine.diagnose(record) is None


def test_terminal_stage_is_never_flagged():
    engine = make_engine()
    record = {
        "token_id": "tok_5",
        "waterfall_stage": "credit_adjustment",
        "current_wq_id": None,
        "eligible_wq_ids": [],
        "hold_reason": "cob_pending",
        "days_in_stage": 999,
    }

    assert engine.diagnose(record) is None


def test_build_zdr_payload_contains_no_token_free_identifiers():
    engine = make_engine()
    findings = engine.diagnose_batch(
        [
            {
                "token_id": "tok_1",
                "waterfall_stage": "follow_up",
                "current_wq_id": "WQ-317",
                "eligible_wq_ids": ["WQ-317"],
                "hold_reason": "cob_pending",
                "days_in_stage": 9,
            }
        ]
    )

    payload = engine.build_zdr_payload(findings)

    assert payload["schema"] == "waterfall_guard.deadlock_diagnosis.v1"
    assert payload["finding_count"] == 1
    assert payload["findings"][0]["token_id"] == "tok_1"
