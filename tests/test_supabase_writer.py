from waterfall_guard.integrations.supabase_writer import SupabaseWriter

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


class FakeQuery:
    def __init__(self, table, rows, on_execute=None):
        self.table = table
        self.rows = rows
        self._on_execute = on_execute

    def execute(self):
        if self._on_execute:
            return self._on_execute(self.table, self.rows)
        return {"data": self.rows}


class FakeTable:
    def __init__(self, name, sink, on_execute=None):
        self.name = name
        self.sink = sink
        self._on_execute = on_execute

    def insert(self, rows):
        self.sink.setdefault(self.name, []).extend(rows)
        return FakeQuery(self.name, rows, self._on_execute)


class FakeSupabaseClient:
    """Stands in for a real supabase-py `Client` so tests never touch the
    network or require the `supabase` package to be installed."""

    def __init__(self, on_execute=None):
        self.sink = {}
        self._on_execute = on_execute

    def table(self, name):
        return FakeTable(name, self.sink, self._on_execute)


def test_writer_is_disabled_when_credentials_are_missing():
    writer = SupabaseWriter(url="", key="")

    assert not writer.enabled
    assert "not configured" in writer.error


def test_write_diagnostic_payload_no_ops_when_disabled():
    writer = SupabaseWriter(url="", key="")

    result = writer.write_diagnostic_payload(SAMPLE_PAYLOAD)

    assert not result.ok
    assert result.written == 0
    assert result.error


def test_writer_soft_fails_when_client_factory_raises():
    def broken_factory(url, key):
        raise ImportError("No module named 'supabase'")

    writer = SupabaseWriter(url="https://proj.supabase.co", key="secret", client_factory=broken_factory)

    assert not writer.enabled
    assert "supabase" in writer.error.lower()

    result = writer.write_diagnostic_payload(SAMPLE_PAYLOAD)
    assert not result.ok
    assert result.written == 0


def test_write_diagnostic_payload_inserts_deidentified_rows():
    fake_client = FakeSupabaseClient()
    writer = SupabaseWriter(
        url="https://proj.supabase.co",
        key="secret",
        table_name="claim_diagnostics",
        client=fake_client,
    )

    result = writer.write_diagnostic_payload(SAMPLE_PAYLOAD)

    assert result.ok
    assert result.written == 1
    assert result.error is None

    [row] = fake_client.sink["claim_diagnostics"]
    assert row["token_id"] == "tok_abc123"
    assert row["waterfall_stage"] == "follow_up"
    assert row["deadlock_types"] == ["no_exit_condition"]
    assert row["eligible_wq_ids"] == ["WQ-317"]


def test_write_diagnostic_payload_contains_no_phi_fields():
    fake_client = FakeSupabaseClient()
    writer = SupabaseWriter(url="https://proj.supabase.co", key="secret", client=fake_client)

    writer.write_diagnostic_payload(SAMPLE_PAYLOAD)

    [row] = fake_client.sink["claim_diagnostics"]
    assert set(row.keys()) == {
        "token_id",
        "waterfall_stage",
        "deadlock_types",
        "active_hold_names",
        "eligible_wq_ids",
        "unassigned_wq_ids",
    }


def test_write_rows_is_a_no_op_success_for_an_empty_batch():
    fake_client = FakeSupabaseClient()
    writer = SupabaseWriter(url="https://proj.supabase.co", key="secret", client=fake_client)

    result = writer.write_rows([])

    assert result.ok
    assert result.written == 0
    assert "claim_diagnostics" not in fake_client.sink


def test_write_rows_soft_fails_when_the_insert_call_raises():
    def on_execute(table, rows):
        raise ConnectionError("could not reach supabase project")

    fake_client = FakeSupabaseClient(on_execute=on_execute)
    writer = SupabaseWriter(url="https://proj.supabase.co", key="secret", client=fake_client)

    result = writer.write_diagnostic_payload(SAMPLE_PAYLOAD)

    assert not result.ok
    assert result.written == 0
    assert "could not reach" in result.error
