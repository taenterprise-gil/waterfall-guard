"""Thin read-only PostgREST client for the Supabase dashboard views.

This client only ever calls the ``vw_*`` views defined in
``scripts/02_create_dashboard_views.sql`` - it has no method for querying
``deadlock_diagnostics`` or ``pipeline_runs`` directly, let alone any raw
Epic/Clarity/Caboodle table. Those views already aggregate over
de-identified data (see ``deident.py``, ``engine.py``), so nothing this
client returns can carry PHI.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from waterfall_guard.config.settings import settings

DEFAULT_TIMEOUT_SECONDS = 10


class SupabaseViewClient:
    """Reads rows from a Supabase view via its auto-generated PostgREST API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        service_role_key: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.base_url = (base_url if base_url is not None else settings.supabase_url).rstrip("/")
        self.service_role_key = (
            service_role_key if service_role_key is not None else settings.supabase_service_role_key
        )
        self.timeout = timeout

    def fetch_view(self, view_name: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Fetch every row of a dashboard view, e.g. ``vw_executive_metrics``."""
        if not self.base_url or not self.service_role_key:
            raise RuntimeError(
                "Supabase is not configured: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
            )

        response = requests.get(
            f"{self.base_url}/rest/v1/{view_name}",
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Accept": "application/json",
            },
            params=params or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
