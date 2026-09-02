import pytest

from waterfall_guard.integrations.epic_client import (
    CaboodleStarSchemaView,
    ClarityExtractParser,
    EpicClient,
    FHIRTaskPoller,
    FHIRTaskStatus,
)


def test_clarity_extract_parser_joins_tables_on_pat_enc_csn_id():
    claims = ClarityExtractParser().parse()

    stalled = next(c for c in claims if c["PAT_ENC_CSN_ID"] == "1002345680")
    assert stalled["PAT_NAME"] == "Nguyen, Trang"
    assert stalled["ACCOUNT_BALANCE"] == 305.00
    assert stalled["WATERFALL_STAGE"] == "follow_up"
    assert stalled["CURRENT_WQ_ID"] == "WQ-204"
    assert stalled["DAYS_IN_STAGE"] == 21


def test_caboodle_current_snapshot_filters_to_is_current_row():
    view = CaboodleStarSchemaView()

    snapshot = view.current_snapshot("1002345680")

    assert snapshot["IS_CURRENT"] is True
    assert snapshot["SNAPSHOT_DATE"] == "2026-08-29"


def test_caboodle_snapshot_history_is_sorted_chronologically():
    view = CaboodleStarSchemaView()

    history = view.snapshot_history("1002345680")

    assert [row["SNAPSHOT_DATE"] for row in history] == ["2026-08-15", "2026-08-29"]


def test_fhir_task_poller_transitions_to_completed():
    poller = FHIRTaskPoller()

    statuses = [poller.poll("job-1") for _ in range(4)]

    assert statuses == [
        FHIRTaskStatus.REQUESTED,
        FHIRTaskStatus.IN_PROGRESS,
        FHIRTaskStatus.IN_PROGRESS,
        FHIRTaskStatus.COMPLETED,
    ]


def test_fhir_task_poller_wait_for_completion_returns_terminal_status():
    poller = FHIRTaskPoller()

    assert poller.wait_for_completion("job-1", max_polls=10) == FHIRTaskStatus.COMPLETED


def test_fhir_task_poller_times_out_if_never_terminal():
    poller = FHIRTaskPoller(transitions=[FHIRTaskStatus.IN_PROGRESS])

    with pytest.raises(TimeoutError):
        poller.wait_for_completion("job-stuck", max_polls=3)


def test_epic_client_fetch_claims_flags_caboodle_stage_drift():
    claims = EpicClient().fetch_claims()

    by_csn = {c["PAT_ENC_CSN_ID"]: c for c in claims}

    # Clarity already shows this claim in follow_up, but Caboodle's current
    # snapshot still has it in claim_edit -> drift.
    assert by_csn["1002345680"]["CABOODLE_STAGE_DRIFT"] is True

    # Everything else's current snapshot agrees with Clarity's live stage.
    assert by_csn["1002345678"]["CABOODLE_STAGE_DRIFT"] is False
    assert by_csn["1002345679"]["CABOODLE_STAGE_DRIFT"] is False
    assert by_csn["1002345681"]["CABOODLE_STAGE_DRIFT"] is False


def test_epic_client_fetch_claims_raises_if_task_never_completes():
    client = EpicClient(task_poller=FHIRTaskPoller(transitions=[FHIRTaskStatus.FAILED]))

    with pytest.raises(RuntimeError):
        client.fetch_claims()
