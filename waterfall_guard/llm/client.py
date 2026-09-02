"""LLM Diagnostic Pipeline: turns an engine deadlock payload into an
actionable root-cause diagnosis via a Zero-Data-Retention (ZDR) LLM call.

Every call this module makes is enforced to run in ZDR mode - no prompt or
completion is retained by the provider - because the input is state/rule
metadata from a hospital's revenue cycle, even though it has already been
scrubbed of PHI by `deident.py`. The transport is injectable so this module
never has to make a live network call to be tested.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import requests

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_RETRIES = 2

SYSTEM_PROMPT = (
    "You are a hospital revenue-cycle diagnostic assistant. You are given a "
    "de-identified list of claim deadlock findings produced by a "
    "rule-vs-waterfall reconciliation engine. No patient-identifying "
    "information is present - every claim is referenced only by an opaque "
    "token_id, and every other field is waterfall stage or work-queue rule "
    "metadata. For each finding, diagnose the root-cause rule collision "
    "and propose an actionable routing fix and a recommended owner/role to "
    "assign it to. Respond as JSON: a list of objects with keys token_id, "
    "root_cause, routing_fix, recommended_owner."
)


@dataclass
class ZDRConfig:
    """Zero-Data-Retention enforcement settings for a provider call.

    `store` must stay False - it maps to a provider's no-retention switch
    (e.g. the `store` param on the OpenAI Responses API). `extra_headers`
    carries whatever HIPAA/BAA-compliance headers the provider contract
    requires (a signed BAA header, a ZDR beta flag, an APIM subscription
    key routed through a HIPAA-eligible endpoint, etc).
    """

    provider: str = "anthropic"
    store: bool = False
    extra_headers: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.store:
            raise ValueError(
                "ZDRConfig.store must be False - this client only supports "
                "Zero-Data-Retention calls"
            )

    def request_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        headers.update(self.extra_headers)
        return headers

    def request_body_overrides(self) -> Dict[str, Any]:
        """Provider-specific fields that must be present to guarantee ZDR."""
        return {"store": self.store}


def build_prompt(zdr_payload: Dict[str, Any]) -> Dict[str, str]:
    """Builds the structured prompt sent to the LLM from an engine payload."""
    return {
        "system": SYSTEM_PROMPT,
        "user": json.dumps(zdr_payload, indent=2),
    }


LLMTransport = Callable[[Dict[str, str], ZDRConfig], str]


def _default_transport(endpoint: str, model: str) -> LLMTransport:
    """A real HTTP transport, used unless a test/demo injects its own."""

    def transport(prompt: Dict[str, str], zdr_config: ZDRConfig) -> str:
        body = {
            "model": model,
            "system": prompt["system"],
            "messages": [{"role": "user", "content": prompt["user"]}],
            **zdr_config.request_body_overrides(),
        }
        response = requests.post(
            endpoint,
            json=body,
            headers=zdr_config.request_headers(),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data.get("content"), list):
            return "".join(part.get("text", "") for part in data["content"])
        if "output_text" in data:
            return data["output_text"]
        return json.dumps(data)

    return transport


@dataclass
class DiagnosticResult:
    raw_text: str
    parsed: Optional[Any]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


class DiagnosticLLMClient:
    """ZDR-enforced client that turns an engine diagnostic payload into an
    actionable root-cause diagnosis."""

    def __init__(
        self,
        transport: Optional[LLMTransport] = None,
        zdr_config: Optional[ZDRConfig] = None,
        model: str = "claude-sonnet-5",
        endpoint: str = "https://api.anthropic.com/v1/messages",
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = 0.0,
    ):
        self.zdr_config = zdr_config or ZDRConfig()
        self.transport = transport or _default_transport(endpoint, model)
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    def diagnose(self, zdr_payload: Dict[str, Any]) -> DiagnosticResult:
        """Sends `zdr_payload` to the LLM and returns its parsed diagnosis.

        Never raises: a failed or timed-out call after all retries comes
        back as a `DiagnosticResult` with `ok=False` and `error` set, so a
        flaky LLM backend can't take down the reconciliation pipeline.
        """
        prompt = build_prompt(zdr_payload)

        last_error: Optional[str] = None
        for attempt in range(self.max_retries + 1):
            try:
                raw_text = self.transport(prompt, self.zdr_config)
            except Exception as exc:  # noqa: BLE001 - any transport failure degrades to a result, never a raise
                last_error = str(exc)
                if attempt < self.max_retries and self.backoff_seconds:
                    time.sleep(self.backoff_seconds * (attempt + 1))
                continue

            return DiagnosticResult(raw_text=raw_text, parsed=self._try_parse(raw_text))

        return DiagnosticResult(
            raw_text="",
            parsed=None,
            error=f"LLM call failed after {self.max_retries + 1} attempt(s): {last_error}",
        )

    @staticmethod
    def _try_parse(raw_text: str) -> Optional[Any]:
        try:
            return json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            return None
