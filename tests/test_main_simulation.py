import json

from waterfall_guard.integrations.supabase_writer import SupabaseWriter
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


def test_run_diagnostic_pipeline_soft_fails_when_supabase_is_unconfigured():
    # No SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY in this environment, so the
    # default writer is disabled - the pipeline must still complete and
    # report the failure rather than raising.
    result = run_diagnostic_pipeline(supabase_writer=SupabaseWriter(url="", key=""))

    assert result["llm_ok"] is True
    assert result["supabase_write_ok"] is False
    assert result["supabase_write_error"]


def test_run_diagnostic_pipeline_persists_findings_when_supabase_is_configured():
    written_rows = []

    class FakeTable:
        def insert(self, rows):
            written_rows.extend(rows)
            return self

        def execute(self):
            return {"data": written_rows}

    class FakeClient:
        def table(self, name):
            return FakeTable()

    writer = SupabaseWriter(url="https://proj.supabase.co", key="secret", client=FakeClient())
    result = run_diagnostic_pipeline(supabase_writer=writer)

    assert result["supabase_write_ok"] is True
    assert len(written_rows) == result["diagnostic_payload"]["finding_count"]
