import pytest

from waterfall_guard.integrations.fhir_writeback_client import (
    EpicFHIRWritebackClient,
    OAuthToken,
    ResolutionStatus,
    ResolutionUpdate,
    TenantEpicConfig,
)

SAMPLE_ROW = {
    "tenant_id": "default",
    "organization_name": "T&A Enterprises",
    "epic_fhir_base_url": "https://fhir.example.org/api/FHIR/R4/",
    "epic_client_id": "test-oauth-client-123",
    "is_onboarding_completed": True,
}


def make_config(**overrides):
    row = {**SAMPLE_ROW, **overrides.pop("row", {})}
    return TenantEpicConfig.from_client_configuration_row(
        row,
        client_secret=overrides.pop("client_secret", "shh"),
        token_url=overrides.pop("token_url", "https://fhir.example.org/oauth2/token"),
    )


# --- TenantEpicConfig --------------------------------------------------------


def test_from_client_configuration_row_strips_trailing_slash():
    config = make_config()

    assert config.fhir_base_url == "https://fhir.example.org/api/FHIR/R4"
    assert config.tenant_id == "default"
    assert config.client_id == "test-oauth-client-123"


def test_from_client_configuration_row_rejects_incomplete_onboarding():
    with pytest.raises(ValueError, match="onboarding"):
        make_config(row={"is_onboarding_completed": False})


def test_from_client_configuration_row_rejects_missing_fhir_url():
    with pytest.raises(ValueError, match="epic_fhir_base_url"):
        make_config(row={"epic_fhir_base_url": ""})


def test_from_client_configuration_row_rejects_missing_client_id():
    with pytest.raises(ValueError, match="epic_client_id"):
        make_config(row={"epic_client_id": None})


def test_from_client_configuration_row_rejects_missing_oauth_secret():
    with pytest.raises(ValueError, match="EPIC_CLIENT_SECRET"):
        make_config(client_secret="")


class FakeQuery:
    def __init__(self, row):
        self._row = row

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return type("Response", (), {"data": self._row})()


class FakeSupabaseClient:
    def __init__(self, row):
        self._row = row

    def table(self, _name):
        return FakeQuery(self._row)


def test_tenant_epic_config_load_builds_from_supabase_row(monkeypatch):
    monkeypatch.setattr(
        "waterfall_guard.integrations.fhir_writeback_client.settings",
        type("S", (), {"epic_client_secret": "shh", "epic_token_url": "https://fhir.example.org/oauth2/token"}),
    )

    config = TenantEpicConfig.load("default", supabase_client=FakeSupabaseClient(SAMPLE_ROW))

    assert config.tenant_id == "default"
    assert config.client_id == "test-oauth-client-123"


def test_tenant_epic_config_load_raises_when_tenant_has_no_row():
    with pytest.raises(ValueError, match="no client_configurations row"):
        TenantEpicConfig.load("ghost-tenant", supabase_client=FakeSupabaseClient(None))


# --- EpicFHIRWritebackClient --------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, headers=None):
        self.status_code = status_code
        self._json_body = json_body or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_body


class FakeSession:
    def __init__(self, get_response=None, put_response=None, get_error=None):
        self.get_response = get_response or FakeResponse(json_body={"resourceType": "Task", "id": "task-1", "status": "requested"})
        self.put_response = put_response or FakeResponse(json_body={"resourceType": "Task", "id": "task-1", "status": "completed"})
        self.get_error = get_error
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, headers))
        if self.get_error:
            raise self.get_error
        return self.get_response

    def put(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("PUT", url, headers, json))
        return self.put_response


def fixed_token_fetcher(access_token="tok-abc", expires_in_calls=None):
    calls = expires_in_calls if expires_in_calls is not None else []

    def fetch(config):
        calls.append(config)
        return OAuthToken(access_token=access_token, expires_at=10_000_000_000.0)

    fetch.calls = calls
    return fetch


def test_post_resolution_completes_task_and_appends_note():
    config = make_config()
    session = FakeSession(
        get_response=FakeResponse(
            json_body={"resourceType": "Task", "id": "task-1", "status": "requested"},
            headers={"ETag": 'W/"3"'},
        )
    )
    client = EpicFHIRWritebackClient(config, session=session, token_fetcher=fixed_token_fetcher())

    result = client.post_resolution(
        ResolutionUpdate(
            task_id="task-1",
            status=ResolutionStatus.RESOLVED,
            note="Corrected WQ routing and released hold.",
            resolved_by="jane.doe@hospital.org",
        )
    )

    assert result.ok
    assert result.fhir_status == "completed"
    assert result.error is None

    put_call = next(c for c in session.calls if c[0] == "PUT")
    _, url, headers, body = put_call
    assert url == "https://fhir.example.org/api/FHIR/R4/Task/task-1"
    assert headers["Authorization"] == "Bearer tok-abc"
    assert headers["If-Match"] == 'W/"3"'
    assert body["status"] == "completed"
    [note] = body["note"]
    assert note["text"] == "Corrected WQ routing and released hold."
    assert note["authorString"] == "jane.doe@hospital.org"


@pytest.mark.parametrize(
    "status, expected_fhir_status",
    [
        (ResolutionStatus.RESOLVED, "completed"),
        (ResolutionStatus.ESCALATED, "in-progress"),
        (ResolutionStatus.WONT_FIX, "cancelled"),
    ],
)
def test_post_resolution_maps_status_to_fhir_task_status(status, expected_fhir_status):
    config = make_config()
    client = EpicFHIRWritebackClient(config, session=FakeSession(), token_fetcher=fixed_token_fetcher())

    result = client.post_resolution(
        ResolutionUpdate(task_id="task-1", status=status, note="n/a", resolved_by="staff")
    )

    assert result.ok
    assert result.fhir_status == expected_fhir_status


def test_post_resolution_omits_if_match_when_no_etag_present():
    config = make_config()
    session = FakeSession(get_response=FakeResponse(json_body={"resourceType": "Task", "id": "task-1"}, headers={}))
    client = EpicFHIRWritebackClient(config, session=session, token_fetcher=fixed_token_fetcher())

    client.post_resolution(
        ResolutionUpdate(task_id="task-1", status=ResolutionStatus.RESOLVED, note="n/a", resolved_by="staff")
    )

    _, _, headers, _ = next(c for c in session.calls if c[0] == "PUT")
    assert "If-Match" not in headers


def test_post_resolution_soft_fails_after_retries_are_exhausted():
    config = make_config()
    session = FakeSession(get_error=ConnectionError("Epic sandbox unreachable"))
    client = EpicFHIRWritebackClient(config, session=session, token_fetcher=fixed_token_fetcher(), max_retries=2)

    result = client.post_resolution(
        ResolutionUpdate(task_id="task-1", status=ResolutionStatus.RESOLVED, note="n/a", resolved_by="staff")
    )

    assert not result.ok
    assert result.task_id == "task-1"
    assert "Epic sandbox unreachable" in result.error
    assert len([c for c in session.calls if c[0] == "GET"]) == 3  # initial attempt + 2 retries


def test_access_token_is_cached_across_calls():
    config = make_config()
    calls = []
    client = EpicFHIRWritebackClient(config, session=FakeSession(), token_fetcher=fixed_token_fetcher(expires_in_calls=calls))

    client.post_resolution(ResolutionUpdate(task_id="task-1", status=ResolutionStatus.RESOLVED, note="n/a", resolved_by="staff"))
    client.post_resolution(ResolutionUpdate(task_id="task-2", status=ResolutionStatus.RESOLVED, note="n/a", resolved_by="staff"))

    assert len(calls) == 1


def test_access_token_is_refetched_once_expired():
    config = make_config()
    session = FakeSession()
    client = EpicFHIRWritebackClient(config, session=session)
    fetch_count = {"n": 0}

    def expiring_fetcher(_config):
        fetch_count["n"] += 1
        return OAuthToken(access_token=f"tok-{fetch_count['n']}", expires_at=0.0)

    client.token_fetcher = expiring_fetcher

    client.post_resolution(ResolutionUpdate(task_id="task-1", status=ResolutionStatus.RESOLVED, note="n/a", resolved_by="staff"))
    client.post_resolution(ResolutionUpdate(task_id="task-2", status=ResolutionStatus.RESOLVED, note="n/a", resolved_by="staff"))

    assert fetch_count["n"] == 2  # one fetch per post_resolution call, not per HTTP request within it
