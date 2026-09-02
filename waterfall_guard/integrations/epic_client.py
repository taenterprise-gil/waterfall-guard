from typing import List

import requests

from waterfall_guard.config.settings import settings
from waterfall_guard.models.claim import Claim


class EpicClient:
    """Thin client over Epic's FHIR R4 claim endpoints."""

    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = base_url or settings.epic_fhir_base_url
        self.token = token

    def _headers(self) -> dict:
        headers = {"Accept": "application/fhir+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def fetch_claims(self, status: str | None = None) -> List[Claim]:
        """Fetch claims from Epic, optionally filtered by status.

        Placeholder: wire up the real FHIR Claim/ClaimResponse search once
        credentials and a sandbox instance are available.
        """
        raise NotImplementedError(
            "EpicClient.fetch_claims is a scaffold; implement FHIR Claim search here."
        )
