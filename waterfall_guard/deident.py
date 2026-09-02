"""Local PHI de-identification layer.

Raw Epic extracts (Clarity-style columns: ``PAT_ENC_CSN_ID``, patient
demographics, account balances, work-queue IDs) are ingested here first,
before anything reaches the reconciliation engine or a downstream LLM call.
Every PHI-bearing field is replaced with an opaque, salted-HMAC token; the
token -> raw-value mapping lives only in this process's memory (the
``PHIVault``) and is never written to disk, logged, or transmitted. The
resulting payload contains nothing but tokens plus non-PHI state and rule
metadata (waterfall stage, WQ IDs, balances, hold reasons), so it is safe to
hand to ``engine.py`` and on to an external, Zero-Data-Retention LLM call.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Epic Clarity-style column names (matched case-insensitively) that carry
# PHI and must never leave this module un-tokenized.
PHI_FIELDS = frozenset(
    {
        "pat_enc_csn_id",
        "pat_id",
        "pat_mrn_id",
        "pat_name",
        "pat_first_name",
        "pat_last_name",
        "birth_date",
        "ssn",
        "address",
        "phone",
        "email",
    }
)

# The field Epic uses to key an encounter; this becomes each record's
# `token_id` once tokenized, and is the join key used for re-identification.
CASE_KEY_FIELDS = ("PAT_ENC_CSN_ID", "pat_enc_csn_id")


class PHIVault:
    """In-memory, salted-HMAC token vault.

    Tokens are deterministic within a single vault instance (same field +
    value always hashes to the same token), so repeated ingests of the same
    patient/encounter correlate without ever storing the raw value outside
    this process. The vault itself never leaves the local runtime.
    """

    def __init__(self, hmac_key: Optional[bytes] = None):
        self._hmac_key = hmac_key or secrets.token_bytes(32)
        self._tokens: Dict[str, Any] = {}

    def tokenize(self, field_name: str, value: Any) -> Optional[str]:
        if value is None:
            return None
        digest = hmac.new(
            self._hmac_key,
            f"{field_name}:{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        token = f"tok_{digest[:24]}"
        self._tokens[token] = value
        return token

    def reidentify(self, token: str) -> Any:
        try:
            return self._tokens[token]
        except KeyError as exc:
            raise KeyError(f"Token {token!r} is not present in this vault") from exc


@dataclass
class DeidentifiedRecord:
    """A de-identified claim record: a correlation token plus non-PHI payload."""

    token_id: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"token_id": self.token_id, **self.payload}

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), default=str)


class Deidentifier:
    """Ingests raw Epic records and produces de-identified payloads."""

    def __init__(self, vault: Optional[PHIVault] = None):
        self.vault = vault or PHIVault()

    def deidentify(self, raw_record: Dict[str, Any]) -> DeidentifiedRecord:
        case_key_field = self._find_case_key_field(raw_record)
        token_id = self.vault.tokenize(case_key_field.lower(), raw_record[case_key_field])

        payload: Dict[str, Any] = {}
        for key, value in raw_record.items():
            if key == case_key_field:
                continue
            normalized_key = key.lower()
            if normalized_key in PHI_FIELDS:
                payload[normalized_key] = self.vault.tokenize(normalized_key, value)
            else:
                payload[normalized_key] = value

        return DeidentifiedRecord(token_id=token_id, payload=payload)

    def deidentify_batch(self, raw_records: List[Dict[str, Any]]) -> List[DeidentifiedRecord]:
        return [self.deidentify(record) for record in raw_records]

    def reidentify(self, record: DeidentifiedRecord) -> Dict[str, Any]:
        """Reverse a de-identified record back to raw PHI using the in-memory vault."""
        restored: Dict[str, Any] = {"PAT_ENC_CSN_ID": self.vault.reidentify(record.token_id)}
        for key, value in record.payload.items():
            if isinstance(value, str) and value.startswith("tok_"):
                restored[key] = self.vault.reidentify(value)
            else:
                restored[key] = value
        return restored

    @staticmethod
    def _find_case_key_field(raw_record: Dict[str, Any]) -> str:
        for candidate in CASE_KEY_FIELDS:
            if candidate in raw_record:
                return candidate
        raise KeyError("raw record is missing a PAT_ENC_CSN_ID field")
