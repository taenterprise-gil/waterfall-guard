import json

from waterfall_guard.main import RAW_CLAIMS, run_simulation

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
