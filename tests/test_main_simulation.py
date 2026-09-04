import json

from waterfall_guard.integrations.supabase_writer import SupabaseWriteError, SupabaseWriter
from waterfall_guard.main import RAW_CLAIMS, run_diagnostic_pipeline, run_simulation

PHI_VALUES = [
    "Doe, Jane",
    "Smith, John",
    "Nguyen, Trang",
    "Alvarez, Maria",
    "1980-04-12",
    "1975-11-02",
    "1990-01-22",
    "1965-06-30",
    "P-99183",
    "P-88214",
    "P-77031",
    "P-66120",
    "1002345678",
    "1002345679",
    "1002345680",
    "1002345681",
]


def test_run_simulation_flags_the_expected_deadlocks():
    payload = run_simulation()

    assert payload["schema"] == "waterfall_guard.deadlock_diagnosis.v1"
    assert payload["finding_count"] == 3

    deadlock_types_by_finding = [set(f["deadlock_types"]) for f in payload["findings"]]
    assert {"no_exit_condition"} in deadlock_types_by_finding
    assert {"ambiguous_wq_routing"} in deadlock_types_by_finding
    assert {"no_escalation_owner"} in deadlock_types_by_finding


def test_run_simulation_payload_contains_no_phi():
    payload = run_simulation()
    serialized = json.dumps(payload)

    for phi_value in PHI_VALUES:
        assert phi_value not in serialized

    # Sanity check the PHI values above actually exist in the source data,
    # so this test would fail loudly if the fixture claims ever change.
    raw_serialized = json.dumps(RAW_CLAIMS)
    for phi_value in PHI_VALUES:
        assert phi_value in raw_serialized


def test_run_diagnostic_pipeline_persists_the_run_and_its_diagnoses():
    recorded_runs = []
    recorded_rows = []

    class RecordingWriter(SupabaseWriter):
        def __init__(self):
            pass

        def record_pipeline_run(self, claims_analyzed, deadlocks_found):
            recorded_runs.append((claims_analyzed, deadlocks_found))

        def record_diagnoses(self, rows):
            recorded_rows.extend(rows)

    result = run_diagnostic_pipeline(supabase_writer=RecordingWriter())

    assert result["persisted"] is True
    assert result["persist_error"] is None
    assert recorded_runs == [(len(RAW_CLAIMS), result["diagnostic_payload"]["finding_count"])]

    # Every finding's token_id got a persisted row, and the dollar amount
    # is a real balance from RAW_CLAIMS - not zero/missing - proving the
    # writer used the same de-identification pass as the findings
    # themselves rather than re-tokenizing (which would mint fresh,
    # mismatched tokens).
    finding_tokens = {f["token_id"] for f in result["diagnostic_payload"]["findings"]}
    row_tokens = {row["token_id"] for row in recorded_rows}
    assert row_tokens == finding_tokens
    assert all(row["dollar_amount_at_risk"] > 0 for row in recorded_rows)


def test_run_diagnostic_pipeline_skips_persistence_when_persist_is_false():
    class ExplodingWriter(SupabaseWriter):
        def __init__(self):
            pass

        def record_pipeline_run(self, claims_analyzed, deadlocks_found):
            raise AssertionError("writer should not be used when persist=False")

    result = run_diagnostic_pipeline(supabase_writer=ExplodingWriter(), persist=False)

    assert result["persisted"] is False
    assert result["persist_error"] is None


def test_run_diagnostic_pipeline_degrades_gracefully_when_supabase_is_unreachable():
    class FailingWriter(SupabaseWriter):
        def __init__(self):
            pass

        def record_pipeline_run(self, claims_analyzed, deadlocks_found):
            raise SupabaseWriteError("Supabase is unreachable")

        def record_diagnoses(self, rows):
            raise AssertionError("should not be reached after record_pipeline_run fails")

    result = run_diagnostic_pipeline(supabase_writer=FailingWriter())

    assert result["llm_ok"] is True
    assert result["persisted"] is False
    assert "unreachable" in result["persist_error"]
