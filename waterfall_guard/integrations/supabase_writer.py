"""Supabase persistence layer for de-identified diagnostic telemetry.

Writes the engine's ZDR-safe deadlock diagnosis payload (see
``engine.build_zdr_payload``) to a Supabase table for downstream reporting.
Every field this module writes has already been de-identified by
``deident.py`` before reaching here - HMAC token IDs plus waterfall
stage/rule metadata - so no PHI is ever persisted.

Soft-fails by design: missing credentials, an uninstalled ``supabase-py``
package, or an unreachable Supabase project all degrade to a disabled
writer / failed ``WriteResult`` rather than raising, so a Supabase outage or
missing config can never take down the reconciliation pipeline (see
``main.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from waterfall_guard.config.settings import settings

DEFAULT_TABLE_NAME = "claim_diagnostics"

SupabaseClientFactory = Callable[[str, str], Any]


def _default_client_factory(url: str, key: str) -> Any:
    """Builds a real supabase-py client.

    Imported lazily so this module (and anything that imports it) loads
    fine even when the ``supabase`` package isn't installed - the
    resulting ``ImportError`` is caught by ``SupabaseWriter`` and just
    disables the writer.
    """
    from supabase import create_client

    return create_client(url, key)


@dataclass
class WriteResult:
    ok: bool
    written: int = 0
    error: Optional[str] = None


class SupabaseWriter:
    """Persists de-identified diagnostic payloads to Supabase.

    Disabled (every write is a no-op ``WriteResult``) whenever
    ``SUPABASE_URL`` or ``SUPABASE_SERVICE_ROLE_KEY`` is unset, the
    ``supabase`` package isn't installed, or the client can't be
    constructed. Never raises.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        table_name: str = DEFAULT_TABLE_NAME,
        client_factory: SupabaseClientFactory = _default_client_factory,
        client: Optional[Any] = None,
    ):
        self.table_name = table_name
        self.url = url if url is not None else settings.supabase_url
        self.key = key if key is not None else settings.supabase_service_role_key
        self.error: Optional[str] = None
        self.client: Optional[Any] = client

        if self.client is None:
            if not self.url or not self.key:
                self.error = "SUPABASE_URL and/or SUPABASE_SERVICE_ROLE_KEY is not configured"
            else:
                try:
                    self.client = client_factory(self.url, self.key)
                except Exception as exc:  # noqa: BLE001 - any construction failure disables the writer, never raises
                    self.error = f"failed to construct Supabase client: {exc}"

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @staticmethod
    def _rows_from_zdr_payload(zdr_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flattens an engine ZDR payload into rows keyed by each claim's
        HMAC token - no PHI, ever."""
        return [
            {
                "token_id": finding["token_id"],
                "waterfall_stage": finding["stage"],
                "deadlock_types": finding["deadlock_types"],
                "active_hold_names": finding["active_hold_names"],
                "eligible_wq_ids": finding["eligible_wq_ids"],
                "unassigned_wq_ids": finding["unassigned_wq_ids"],
            }
            for finding in zdr_payload.get("findings", [])
        ]

    def write_diagnostic_payload(self, zdr_payload: Dict[str, Any]) -> WriteResult:
        """Writes an engine ZDR payload's findings as rows. Never raises."""
        return self.write_rows(self._rows_from_zdr_payload(zdr_payload))

    def write_rows(self, rows: List[Dict[str, Any]]) -> WriteResult:
        if not self.enabled:
            return WriteResult(ok=False, written=0, error=self.error or "Supabase writer is disabled")
        if not rows:
            return WriteResult(ok=True, written=0)
        try:
            self.client.table(self.table_name).insert(rows).execute()
        except Exception as exc:  # noqa: BLE001 - a write failure degrades to a result, never a raise
            return WriteResult(ok=False, written=0, error=str(exc))
        return WriteResult(ok=True, written=len(rows))
