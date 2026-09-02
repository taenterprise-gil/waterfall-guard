import pytest

from waterfall_guard.deident import Deidentifier, PHIVault

RAW_RECORD = {
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
}


def test_deidentify_tokenizes_phi_fields():
    record = Deidentifier().deidentify(RAW_RECORD)

    assert record.token_id.startswith("tok_")
    assert record.payload["pat_id"].startswith("tok_")
    assert record.payload["pat_name"].startswith("tok_")
    assert record.payload["birth_date"].startswith("tok_")

    for phi_value in ("1002345678", "P-99183", "Doe, Jane", "1980-04-12"):
        assert phi_value not in record.payload.values()
        assert phi_value != record.token_id


def test_deidentify_preserves_non_phi_state_and_rule_metadata():
    record = Deidentifier().deidentify(RAW_RECORD)

    assert record.payload["account_balance"] == 482.13
    assert record.payload["waterfall_stage"] == "follow_up"
    assert record.payload["current_wq_id"] == "WQ-317"
    assert record.payload["eligible_wq_ids"] == ["WQ-317"]
    assert record.payload["hold_reason"] == "cob_pending"
    assert record.payload["days_in_stage"] == 9


def test_deidentify_is_deterministic_within_a_vault():
    deidentifier = Deidentifier()
    first = deidentifier.deidentify(RAW_RECORD)
    second = deidentifier.deidentify(RAW_RECORD)

    assert first.token_id == second.token_id
    assert first.payload["pat_id"] == second.payload["pat_id"]


def test_deidentify_tokens_differ_across_vaults():
    first = Deidentifier(PHIVault()).deidentify(RAW_RECORD)
    second = Deidentifier(PHIVault()).deidentify(RAW_RECORD)

    assert first.token_id != second.token_id


def test_reidentify_round_trip_restores_raw_values():
    deidentifier = Deidentifier()
    record = deidentifier.deidentify(RAW_RECORD)

    restored = deidentifier.reidentify(record)

    assert restored["PAT_ENC_CSN_ID"] == RAW_RECORD["PAT_ENC_CSN_ID"]
    assert restored["pat_id"] == RAW_RECORD["PAT_ID"]
    assert restored["pat_name"] == RAW_RECORD["PAT_NAME"]
    assert restored["birth_date"] == RAW_RECORD["BIRTH_DATE"]
    assert restored["account_balance"] == RAW_RECORD["ACCOUNT_BALANCE"]


def test_reidentify_unknown_token_raises():
    with pytest.raises(KeyError):
        PHIVault().reidentify("tok_does_not_exist")


def test_deidentify_missing_case_key_raises():
    with pytest.raises(KeyError):
        Deidentifier().deidentify({"PAT_ID": "P-1"})
