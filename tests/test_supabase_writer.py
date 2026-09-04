import pytest
import requests

from waterfall_guard.integrations.supabase_writer import (
    SupabaseWriteError,
    SupabaseWriter,
    build_diagnostic_rows,
)

FINDINGS_PAYLOAD = {
    "schema": "waterfall_guard.deadlock_diagnosis.v1",
    "finding_count": 2,
    "findings": [
        {
            "token_id": "tok_a",
            "stage": "follow_up",
            "deadlock_types": ["no_exit_condition"],
            "active_hold_names": ["coordination_of_benefits_pending"],
            "eligible_wq_ids": ["WQ-317"],
            "unassigned_wq_ids": ["WQ-317"],
        },
        {
            "token_id": "tok_b",
            "stage": "follow_up",
            "deadlock_types": ["ambiguous_wq_routing", "no_escalation_owner"],
            "active_hold_names": [],
            "eligible_wq_ids": ["WQ-204", "WQ-317"],
            "unassigned_wq_ids": ["WQ-204", "WQ-317"],
        },
    ],
}

DIAGNOSES = [
    {
        "token_id": "tok_a",
        "root_cause": "no WQ resolves this hold",
        "routing_fix": "add a resolving WQ",
        "recommended_owner": "revenue_cycle_supervisor",
    }
    # tok_b has no matching diagnosis - simulates a partial LLM response.
]

DOLLARS_BY_TOKEN = {"tok_a": 482.13, "tok_b": 1210.55}


def test_build_diagnostic_rows_uses_the_primary_deadlock_type_and_matches_diagnoses_by_token():
    rows = build_diagnostic_rows(FINDINGS_PAYLOAD, DIAGNOSES, DOLLARS_BY_TOKEN)

    assert len(rows) == 2
    row_a, row_b = rows

    assert row_a == {
        "token_id": "tok_a",
        "waterfall_stage": "follow_up",
        "deadlock_type": "no_exit_condition",
        "root_cause": "no WQ resolves this hold",
        "routing_fix": "add a resolving WQ",
        "recommended_owner": "revenue_cycle_supervisor",
        "dollar_amount_at_risk": 482.13,
    }
    # tok_b carries two deadlock_types; only the first becomes the row's
    # category so vw_executive_metrics doesn't double-count its balance.
    assert row_b["deadlock_type"] == "ambiguous_wq_routing"
    assert row_b["dollar_amount_at_risk"] == 1210.55
    # No matching diagnosis for tok_b - fields degrade to None, not KeyError.
    assert row_b["root_cause"] is None
    assert row_b["recommended_owner"] is None


def test_build_diagnostic_rows_defaults_missing_dollar_amount_to_zero():
    rows = build_diagnostic_rows(FINDINGS_PAYLOAD, DIAGNOSES, {})

    assert all(row["dollar_amount_at_risk"] == 0 for row in rows)


def test_build_diagnostic_rows_handles_an_empty_findings_payload():
    empty_payload = {"schema": "waterfall_guard.deadlock_diagnosis.v1", "finding_count": 0, "findings": []}

    assert build_diagnostic_rows(empty_payload, DIAGNOSES, DOLLARS_BY_TOKEN) == []


def test_record_pipeline_run_posts_a_single_row_to_the_pipeline_runs_table():
    seen = {}

    def fake_transport(url, rows, headers, timeout):
        seen["url"] = url
        seen["rows"] = rows
        seen["headers"] = headers

    writer = SupabaseWriter(
        base_url="https://demo.supabase.co", service_role_key="test-key", transport=fake_transport
    )
    writer.record_pipeline_run(claims_analyzed=4, deadlocks_found=3)

    assert seen["url"] == "https://demo.supabase.co/rest/v1/pipeline_runs"
    assert seen["rows"] == [{"claims_analyzed": 4, "deadlocks_found": 3}]
    assert seen["headers"]["apikey"] == "test-key"
    assert seen["headers"]["Authorization"] == "Bearer test-key"


def test_record_diagnoses_posts_all_rows_to_the_deadlock_diagnostics_table():
    seen = {}

    def fake_transport(url, rows, headers, timeout):
        seen["url"] = url
        seen["rows"] = rows

    writer = SupabaseWriter(
        base_url="https://demo.supabase.co", service_role_key="test-key", transport=fake_transport
    )
    rows = build_diagnostic_rows(FINDINGS_PAYLOAD, DIAGNOSES, DOLLARS_BY_TOKEN)
    writer.record_diagnoses(rows)

    assert seen["url"] == "https://demo.supabase.co/rest/v1/deadlock_diagnostics"
    assert seen["rows"] == rows


def test_record_diagnoses_is_a_no_op_when_there_are_no_rows():
    def fake_transport(url, rows, headers, timeout):
        raise AssertionError("transport should not be called for an empty write")

    writer = SupabaseWriter(
        base_url="https://demo.supabase.co", service_role_key="test-key", transport=fake_transport
    )

    writer.record_diagnoses([])  # must not raise or call the transport


def test_writer_raises_a_clean_error_when_supabase_is_not_configured():
    writer = SupabaseWriter(base_url="", service_role_key="", transport=lambda *a, **k: None)

    with pytest.raises(SupabaseWriteError):
        writer.record_pipeline_run(claims_analyzed=1, deadlocks_found=0)


def test_writer_wraps_a_transport_failure_as_a_supabase_write_error():
    def failing_transport(url, rows, headers, timeout):
        raise requests.RequestException("connection refused")

    writer = SupabaseWriter(
        base_url="https://demo.supabase.co", service_role_key="test-key", transport=failing_transport
    )

    with pytest.raises(SupabaseWriteError):
        writer.record_pipeline_run(claims_analyzed=1, deadlocks_found=0)
