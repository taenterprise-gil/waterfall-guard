import json

import pytest

from waterfall_guard.llm.client import DiagnosticLLMClient, ZDRConfig, build_prompt

SAMPLE_PAYLOAD = {
    "schema": "waterfall_guard.deadlock_diagnosis.v1",
    "finding_count": 1,
    "findings": [
        {
            "token_id": "tok_abc123",
            "stage": "follow_up",
            "deadlock_types": ["no_exit_condition"],
            "active_hold_names": ["coordination_of_benefits_pending"],
            "eligible_wq_ids": ["WQ-317"],
            "unassigned_wq_ids": ["WQ-317"],
        }
    ],
}


def test_zdr_config_rejects_store_true():
    with pytest.raises(ValueError):
        ZDRConfig(store=True)


def test_zdr_config_enforces_store_false_and_merges_compliance_headers():
    config = ZDRConfig(extra_headers={"x-hipaa-baa": "signed"})

    assert config.request_body_overrides() == {"store": False}
    headers = config.request_headers()
    assert headers["x-hipaa-baa"] == "signed"
    assert headers["Content-Type"] == "application/json"


def test_build_prompt_instructs_root_cause_routing_fix_and_owner():
    prompt = build_prompt(SAMPLE_PAYLOAD)

    lowered = prompt["system"].lower()
    assert "root-cause" in lowered or "root cause" in lowered
    assert "routing" in lowered
    assert "owner" in lowered


def test_build_prompt_embeds_the_full_payload_verbatim():
    prompt = build_prompt(SAMPLE_PAYLOAD)

    assert json.loads(prompt["user"]) == SAMPLE_PAYLOAD
    assert "tok_abc123" in prompt["user"]


def test_diagnose_sends_zdr_enforced_request_and_returns_parsed_diagnosis():
    seen_zdr_configs = []

    def fake_transport(prompt, zdr_config):
        seen_zdr_configs.append(zdr_config)
        payload = json.loads(prompt["user"])
        return json.dumps(
            [
                {
                    "token_id": finding["token_id"],
                    "root_cause": "no WQ resolves this hold",
                    "routing_fix": "add a resolving WQ",
                    "recommended_owner": "revenue_cycle_supervisor",
                }
                for finding in payload["findings"]
            ]
        )

    client = DiagnosticLLMClient(transport=fake_transport)
    result = client.diagnose(SAMPLE_PAYLOAD)

    assert result.ok
    assert result.error is None
    assert result.parsed[0]["token_id"] == "tok_abc123"
    assert result.parsed[0]["recommended_owner"] == "revenue_cycle_supervisor"
    assert len(seen_zdr_configs) == 1
    assert seen_zdr_configs[0].store is False


def test_diagnose_falls_back_gracefully_when_transport_always_fails():
    def failing_transport(prompt, zdr_config):
        raise TimeoutError("upstream timed out")

    client = DiagnosticLLMClient(transport=failing_transport, max_retries=1)
    result = client.diagnose(SAMPLE_PAYLOAD)

    assert not result.ok
    assert result.parsed is None
    assert "timed out" in result.error


def test_diagnose_retries_before_succeeding():
    calls = {"count": 0}

    def flaky_transport(prompt, zdr_config):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ConnectionError("temporary blip")
        return json.dumps(
            [
                {
                    "token_id": "tok_abc123",
                    "root_cause": "ok",
                    "routing_fix": "ok",
                    "recommended_owner": "ok",
                }
            ]
        )

    client = DiagnosticLLMClient(transport=flaky_transport, max_retries=2)
    result = client.diagnose(SAMPLE_PAYLOAD)

    assert result.ok
    assert calls["count"] == 2


def test_diagnose_handles_a_non_json_response_without_crashing():
    def text_transport(prompt, zdr_config):
        return "Sorry, I can't help with that."

    client = DiagnosticLLMClient(transport=text_transport)
    result = client.diagnose(SAMPLE_PAYLOAD)

    assert result.ok
    assert result.parsed is None
    assert result.raw_text.startswith("Sorry")
