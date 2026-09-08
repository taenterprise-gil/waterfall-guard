"""Epic FHIR write-back client.

Unlike ``epic_client.py``'s read-side mocks, this makes a real HTTP call: it
lets staff post a resolution status update for a deadlocked claim back to
Epic as a FHIR ``Task`` update, authenticating per-tenant via OAuth2
client_credentials against that tenant's ``client_configurations`` row
(``epic_fhir_base_url`` / ``epic_client_id``). ``client_configurations`` has
no per-tenant OAuth secret/token URL column yet, so those still come from
``EPIC_CLIENT_SECRET`` / ``EPIC_TOKEN_URL`` in ``config/settings.py``.

Config loading raises on a missing/incomplete tenant setup (a fixable setup
problem the caller should surface immediately), but the write-back call
itself never raises: a network failure degrades to a failed
``WritebackResult`` after retries, matching ``llm/client.py`` and
``supabase_writer.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional

import requests

from waterfall_guard.config.settings import settings

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_RETRIES = 2
TOKEN_EXPIRY_LEEWAY_SECONDS = 30
CONFIG_TABLE_NAME = "client_configurations"


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    WONT_FIX = "wont_fix"


_RESOLUTION_TO_FHIR_TASK_STATUS = {
    ResolutionStatus.RESOLVED: "completed",
    ResolutionStatus.ESCALATED: "in-progress",
    ResolutionStatus.WONT_FIX: "cancelled",
}


@dataclass
class TenantEpicConfig:
    """Per-tenant Epic FHIR connection settings."""

    tenant_id: str
    fhir_base_url: str
    client_id: str
    client_secret: str
    token_url: str

    @classmethod
    def from_client_configuration_row(
        cls,
        row: Dict[str, Any],
        client_secret: str,
        token_url: str,
    ) -> "TenantEpicConfig":
        tenant_id = row.get("tenant_id") or ""
        fhir_base_url = (row.get("epic_fhir_base_url") or "").rstrip("/")
        client_id = row.get("epic_client_id") or ""
        if not row.get("is_onboarding_completed"):
            raise ValueError(f"tenant {tenant_id!r} has not completed onboarding")
        if not fhir_base_url or not client_id:
            raise ValueError(
                f"tenant {tenant_id!r} is missing epic_fhir_base_url/epic_client_id "
                "in client_configurations"
            )
        if not client_secret or not token_url:
            raise ValueError("EPIC_CLIENT_SECRET and/or EPIC_TOKEN_URL is not configured")
        return cls(
            tenant_id=tenant_id,
            fhir_base_url=fhir_base_url,
            client_id=client_id,
            client_secret=client_secret,
            token_url=token_url,
        )

    @classmethod
    def load(cls, tenant_id: str, supabase_client: Optional[Any] = None) -> "TenantEpicConfig":
        """Fetches `tenant_id`'s row from client_configurations and builds
        a config from it. Raises ValueError if the tenant isn't onboarded
        or Supabase/OAuth settings are missing - there's no reasonable
        no-op fallback for an explicit staff write-back action."""
        client = supabase_client or _default_supabase_client()
        response = (
            client.table(CONFIG_TABLE_NAME)
            .select("*")
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        row = response.data if response is not None else None
        if not row:
            raise ValueError(f"no client_configurations row for tenant {tenant_id!r}")
        return cls.from_client_configuration_row(
            row,
            client_secret=settings.epic_client_secret,
            token_url=settings.epic_token_url,
        )


def _default_supabase_client() -> Any:
    """Imported lazily so this module loads fine without the `supabase`
    package installed, matching supabase_writer.py's convention."""
    from supabase import create_client

    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise ValueError("SUPABASE_URL and/or SUPABASE_SERVICE_ROLE_KEY is not configured")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


@dataclass
class OAuthToken:
    access_token: str
    expires_at: float  # time.monotonic() deadline


TokenFetcher = Callable[[TenantEpicConfig], OAuthToken]


def _default_token_fetcher(config: TenantEpicConfig) -> OAuthToken:
    response = requests.post(
        config.token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        },
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()
    expires_in = float(body.get("expires_in", 300))
    return OAuthToken(
        access_token=body["access_token"],
        expires_at=time.monotonic() + expires_in - TOKEN_EXPIRY_LEEWAY_SECONDS,
    )


@dataclass
class ResolutionUpdate:
    task_id: str
    status: ResolutionStatus
    note: str
    resolved_by: str


@dataclass
class WritebackResult:
    ok: bool
    task_id: str
    fhir_status: Optional[str] = None
    error: Optional[str] = None


class EpicFHIRWritebackClient:
    """Posts resolution status updates for deadlocked claims to Epic's FHIR
    Task endpoint, authenticating per-tenant via OAuth2 client_credentials."""

    def __init__(
        self,
        config: TenantEpicConfig,
        session: Optional[requests.Session] = None,
        token_fetcher: Optional[TokenFetcher] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = 0.0,
    ):
        self.config = config
        self.session = session or requests.Session()
        self.token_fetcher = token_fetcher or _default_token_fetcher
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._token: Optional[OAuthToken] = None

    @classmethod
    def for_tenant(cls, tenant_id: str, **kwargs: Any) -> "EpicFHIRWritebackClient":
        return cls(TenantEpicConfig.load(tenant_id), **kwargs)

    def _access_token(self) -> str:
        if self._token is None or time.monotonic() >= self._token.expires_at:
            self._token = self.token_fetcher(self.config)
        return self._token.access_token

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "Accept": "application/fhir+json",
        }

    def post_resolution(self, update: ResolutionUpdate) -> WritebackResult:
        """Applies `update` to the claim's FHIR Task and PUTs it back to
        Epic. Never raises: a failed call after all retries comes back as
        a WritebackResult with ok=False, so a flaky Epic endpoint can't
        take down the caller (e.g. the dashboard action that triggered it).
        """
        last_error: Optional[str] = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._post_resolution_once(update)
            except Exception as exc:  # noqa: BLE001 - any failure degrades to a result, never a raise
                last_error = str(exc)
                if attempt < self.max_retries and self.backoff_seconds:
                    time.sleep(self.backoff_seconds * (attempt + 1))
        return WritebackResult(ok=False, task_id=update.task_id, error=last_error)

    def _post_resolution_once(self, update: ResolutionUpdate) -> WritebackResult:
        url = f"{self.config.fhir_base_url}/Task/{update.task_id}"
        # Fetched once and reused for both requests below - the GET/PUT pair
        # is one logical operation, so re-checking token expiry mid-way
        # would only risk racing a refresh against itself for no benefit.
        auth_headers = self._auth_headers()

        get_response = self.session.get(url, headers=auth_headers, timeout=DEFAULT_TIMEOUT_SECONDS)
        get_response.raise_for_status()
        task = get_response.json()

        fhir_status = _RESOLUTION_TO_FHIR_TASK_STATUS[update.status]
        task["status"] = fhir_status
        task.setdefault("note", []).append(
            {
                "text": update.note,
                "authorString": update.resolved_by,
                "time": datetime.now(timezone.utc).isoformat(),
            }
        )

        headers = {**auth_headers, "Content-Type": "application/fhir+json"}
        # Epic supports versioned updates via ETag; sending it back as
        # If-Match rejects the write instead of clobbering a concurrent
        # Epic-side edit made since our GET.
        etag = get_response.headers.get("ETag")
        if etag:
            headers["If-Match"] = etag

        put_response = self.session.put(url, json=task, headers=headers, timeout=DEFAULT_TIMEOUT_SECONDS)
        put_response.raise_for_status()

        return WritebackResult(ok=True, task_id=update.task_id, fhir_status=fhir_status)
