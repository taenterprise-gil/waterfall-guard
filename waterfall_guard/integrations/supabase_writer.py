"""Writer that persists a pipeline run's de-identified findings and
diagnoses into the Supabase tables the Phase 2 dashboard views read from
(see ``scripts/01_create_diagnostic_tables.sql``).

Only ever accepts the de-identified shapes ``engine.py``/``llm/client.py``
already produce - an opaque ``token_id``, waterfall/rule metadata, and a
dollar amount - never a raw Epic record. This module has no method that
takes a raw claim or PHI field, so it cannot leak one.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import requests

from waterfall_guard.config.settings import settings

DEFAULT_TIMEOUT_SECONDS = 10


class SupabaseWriteError(RuntimeError):
    """Raised when a write to a Supabase table fails or Supabase isn't configured."""


# Injectable so tests never need a live Supabase project, mirroring the
# LLMTransport pattern in llm/client.py.
InsertTransport = Callable[[str, List[Dict[str, Any]], Dict[str, str], float], None]


def _default_insert_transport(url: str, rows: List[Dict[str, Any]], headers: Dict[str, str], timeout: float) -> None:
    response = requests.post(url, json=rows, headers=headers, timeout=timeout)
    response.raise_for_status()


def build_diagnostic_rows(
    findings_payload: Dict[str, Any],
    diagnoses: List[Dict[str, Any]],
    dollar_amounts_by_token: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Builds ``deadlock_diagnostics`` rows for one pipeline run.

    One row per finding, not per ``deadlock_types`` entry: a finding can
    carry more than one deadlock type at once, but ``dollar_amount_at_risk``
    is the claim's own balance, and ``vw_executive_metrics`` sums this
    column across rows - emitting a row per type would double-count that
    balance for any claim with more than one concurrent deadlock. The
    first ``deadlock_types`` entry becomes the row's category.

    A finding with no matching diagnosis (LLM call failed, or returned a
    partial list) still gets a row - the narrative fields just come back
    ``None`` rather than being dropped from the run entirely.
    """
    diagnoses_by_token = {
        diagnosis["token_id"]: diagnosis
        for diagnosis in diagnoses
        if isinstance(diagnosis, dict) and "token_id" in diagnosis
    }

    rows = []
    for finding in findings_payload.get("findings", []):
        token_id = finding["token_id"]
        diagnosis = diagnoses_by_token.get(token_id, {})
        deadlock_types = finding.get("deadlock_types") or ["unknown"]
        rows.append(
            {
                "token_id": token_id,
                "waterfall_stage": finding["stage"],
                "deadlock_type": deadlock_types[0],
                "root_cause": diagnosis.get("root_cause"),
                "routing_fix": diagnosis.get("routing_fix"),
                "recommended_owner": diagnosis.get("recommended_owner"),
                "dollar_amount_at_risk": dollar_amounts_by_token.get(token_id) or 0,
            }
        )
    return rows


class SupabaseWriter:
    """Inserts rows into ``pipeline_runs`` and ``deadlock_diagnostics`` -
    the base tables backing the dashboard views. Never touches a ``vw_*``
    view; ``SupabaseViewClient`` (``api/supabase_client.py``) is the read
    side of this split.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        service_role_key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Optional[InsertTransport] = None,
    ):
        self.base_url = (base_url if base_url is not None else settings.supabase_url).rstrip("/")
        self.service_role_key = (
            service_role_key if service_role_key is not None else settings.supabase_service_role_key
        )
        self.timeout = timeout
        self.transport = transport or _default_insert_transport

    def _insert(self, table_name: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        if not self.base_url or not self.service_role_key:
            raise SupabaseWriteError(
                "Supabase is not configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
            )

        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
        try:
            self.transport(f"{self.base_url}/rest/v1/{table_name}", rows, headers, self.timeout)
        except requests.RequestException as exc:
            raise SupabaseWriteError(f"Failed to write to {table_name}: {exc}") from exc

    def record_pipeline_run(self, claims_analyzed: int, deadlocks_found: int) -> None:
        self._insert(
            "pipeline_runs",
            [{"claims_analyzed": claims_analyzed, "deadlocks_found": deadlocks_found}],
        )

    def record_diagnoses(self, rows: List[Dict[str, Any]]) -> None:
        self._insert("deadlock_diagnostics", rows)
