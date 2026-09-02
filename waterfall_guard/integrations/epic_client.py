"""Epic ingestion layer.

Simulates the three integration points a live deployment needs:

- a **Clarity** SQL extract, joined across relational tables by
  ``PAT_ENC_CSN_ID`` (Epic's normalized operational reporting database);
- a **Caboodle** star-schema snapshot view, where dimension rows carry a
  ``SNAPSHOT_DATE``/``IS_CURRENT`` flag (Epic's enterprise data warehouse,
  refreshed on a nightly ETL cadence, so its "current" snapshot can still
  lag what Clarity shows live);
- a **FHIR ``Task``** resource the async extract job is tracked under.

Nothing here makes a network call; it's mock data standing in for a live
Epic sandbox until real credentials are available (see ``config/settings.py``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# --- Mock Clarity relational tables -----------------------------------------
# Clarity's schema is normalized; a real extract joins several tables on
# PAT_ENC_CSN_ID (the encounter contact serial number) into one claim-shaped
# row. These stand in for PAT_ENC, PATIENT, ACCOUNT, and a WQ status table.

_PAT_ENC: List[Dict[str, Any]] = [
    {"PAT_ENC_CSN_ID": "1002345678", "PAT_ID": "P-99183"},
    {"PAT_ENC_CSN_ID": "1002345679", "PAT_ID": "P-88214"},
    {"PAT_ENC_CSN_ID": "1002345680", "PAT_ID": "P-77031"},
    {"PAT_ENC_CSN_ID": "1002345681", "PAT_ID": "P-66120"},
]

_PATIENT: List[Dict[str, Any]] = [
    {"PAT_ID": "P-99183", "PAT_NAME": "Doe, Jane", "BIRTH_DATE": "1980-04-12"},
    {"PAT_ID": "P-88214", "PAT_NAME": "Smith, John", "BIRTH_DATE": "1975-11-02"},
    {"PAT_ID": "P-77031", "PAT_NAME": "Nguyen, Trang", "BIRTH_DATE": "1990-01-22"},
    {"PAT_ID": "P-66120", "PAT_NAME": "Alvarez, Maria", "BIRTH_DATE": "1965-06-30"},
]

_ACCOUNT: List[Dict[str, Any]] = [
    {"PAT_ENC_CSN_ID": "1002345678", "ACCOUNT_BALANCE": 482.13},
    {"PAT_ENC_CSN_ID": "1002345679", "ACCOUNT_BALANCE": 1210.55},
    {"PAT_ENC_CSN_ID": "1002345680", "ACCOUNT_BALANCE": 305.00},
    {"PAT_ENC_CSN_ID": "1002345681", "ACCOUNT_BALANCE": 87.40},
]

_CLARITY_WQ: List[Dict[str, Any]] = [
    {
        "PAT_ENC_CSN_ID": "1002345678",
        "WATERFALL_STAGE": "follow_up",
        "CURRENT_WQ_ID": "WQ-317",
        "ELIGIBLE_WQ_IDS": ["WQ-317"],
        "HOLD_REASON": "cob_pending",
        "DAYS_IN_STAGE": 9,
    },
    {
        "PAT_ENC_CSN_ID": "1002345679",
        "WATERFALL_STAGE": "follow_up",
        "CURRENT_WQ_ID": "WQ-204",
        "ELIGIBLE_WQ_IDS": ["WQ-204", "WQ-317"],
        "HOLD_REASON": None,
        "DAYS_IN_STAGE": 4,
    },
    {
        "PAT_ENC_CSN_ID": "1002345680",
        "WATERFALL_STAGE": "follow_up",
        "CURRENT_WQ_ID": "WQ-204",
        "ELIGIBLE_WQ_IDS": ["WQ-204"],
        "HOLD_REASON": None,
        "DAYS_IN_STAGE": 21,
    },
    {
        "PAT_ENC_CSN_ID": "1002345681",
        "WATERFALL_STAGE": "claim_edit",
        "CURRENT_WQ_ID": "WQ-EDIT-CORRECT",
        "ELIGIBLE_WQ_IDS": ["WQ-EDIT-CORRECT"],
        "HOLD_REASON": "missing_modifier",
        "DAYS_IN_STAGE": 2,
    },
]


class ClarityExtractParser:
    """Joins the mock Clarity tables above into claim-shaped rows.

    A real implementation replaces the module-level tables with the result
    of actual SQL queries against Clarity, joined the same way: PAT_ENC ->
    PATIENT via PAT_ID, PAT_ENC -> ACCOUNT/CLARITY_WQ via PAT_ENC_CSN_ID.
    """

    def __init__(
        self,
        pat_enc: Optional[List[Dict[str, Any]]] = None,
        patient: Optional[List[Dict[str, Any]]] = None,
        account: Optional[List[Dict[str, Any]]] = None,
        clarity_wq: Optional[List[Dict[str, Any]]] = None,
    ):
        self.pat_enc = pat_enc if pat_enc is not None else _PAT_ENC
        self.patient = patient if patient is not None else _PATIENT
        self.account = account if account is not None else _ACCOUNT
        self.clarity_wq = clarity_wq if clarity_wq is not None else _CLARITY_WQ

    def parse(self) -> List[Dict[str, Any]]:
        patient_by_id = {row["PAT_ID"]: row for row in self.patient}
        account_by_csn = {row["PAT_ENC_CSN_ID"]: row for row in self.account}
        wq_by_csn = {row["PAT_ENC_CSN_ID"]: row for row in self.clarity_wq}

        claims = []
        for enc in self.pat_enc:
            csn = enc["PAT_ENC_CSN_ID"]
            patient = patient_by_id.get(enc["PAT_ID"], {})
            account = account_by_csn.get(csn, {})
            wq = wq_by_csn.get(csn, {})

            claims.append(
                {
                    "PAT_ENC_CSN_ID": csn,
                    "PAT_ID": enc["PAT_ID"],
                    "PAT_NAME": patient.get("PAT_NAME"),
                    "BIRTH_DATE": patient.get("BIRTH_DATE"),
                    "ACCOUNT_BALANCE": account.get("ACCOUNT_BALANCE"),
                    "WATERFALL_STAGE": wq.get("WATERFALL_STAGE"),
                    "CURRENT_WQ_ID": wq.get("CURRENT_WQ_ID"),
                    "ELIGIBLE_WQ_IDS": wq.get("ELIGIBLE_WQ_IDS", []),
                    "HOLD_REASON": wq.get("HOLD_REASON"),
                    "DAYS_IN_STAGE": wq.get("DAYS_IN_STAGE"),
                }
            )
        return claims


# --- Mock Caboodle star-schema view -----------------------------------------
# Caboodle dimension rows are versioned SCD-Type-2 style, with a
# SNAPSHOT_DATE and an IS_CURRENT flag, refreshed nightly - so the "current"
# snapshot can still lag what Clarity shows live. Claim 1002345680 below
# models exactly that: Clarity already shows it in follow_up, but the last
# Caboodle ETL snapshot still has it in claim_edit.

_CABOODLE_CLAIM_STATUS_FACT: List[Dict[str, Any]] = [
    {"PAT_ENC_CSN_ID": "1002345678", "SNAPSHOT_DATE": "2026-08-24", "IS_CURRENT": False, "WATERFALL_STAGE": "claim_edit"},
    {"PAT_ENC_CSN_ID": "1002345678", "SNAPSHOT_DATE": "2026-09-01", "IS_CURRENT": True, "WATERFALL_STAGE": "follow_up"},
    {"PAT_ENC_CSN_ID": "1002345679", "SNAPSHOT_DATE": "2026-09-01", "IS_CURRENT": True, "WATERFALL_STAGE": "follow_up"},
    {"PAT_ENC_CSN_ID": "1002345680", "SNAPSHOT_DATE": "2026-08-15", "IS_CURRENT": False, "WATERFALL_STAGE": "claim_edit"},
    {"PAT_ENC_CSN_ID": "1002345680", "SNAPSHOT_DATE": "2026-08-29", "IS_CURRENT": True, "WATERFALL_STAGE": "claim_edit"},
    {"PAT_ENC_CSN_ID": "1002345681", "SNAPSHOT_DATE": "2026-09-01", "IS_CURRENT": True, "WATERFALL_STAGE": "claim_edit"},
]


class CaboodleStarSchemaView:
    """Reads the mock Caboodle fact table the way a BI query would:
    ``WHERE IsCurrent = 1``."""

    def __init__(self, fact_table: Optional[List[Dict[str, Any]]] = None):
        self.fact_table = fact_table if fact_table is not None else _CABOODLE_CLAIM_STATUS_FACT

    def current_snapshot(self, pat_enc_csn_id: str) -> Optional[Dict[str, Any]]:
        for row in self.fact_table:
            if row["PAT_ENC_CSN_ID"] == pat_enc_csn_id and row["IS_CURRENT"]:
                return row
        return None

    def snapshot_history(self, pat_enc_csn_id: str) -> List[Dict[str, Any]]:
        rows = [row for row in self.fact_table if row["PAT_ENC_CSN_ID"] == pat_enc_csn_id]
        return sorted(rows, key=lambda row: row["SNAPSHOT_DATE"])


# --- Mock FHIR Task polling --------------------------------------------------


class FHIRTaskStatus(str, Enum):
    REQUESTED = "requested"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    FAILED = "failed"


_TERMINAL_TASK_STATUSES = frozenset({FHIRTaskStatus.COMPLETED, FHIRTaskStatus.FAILED})


@dataclass
class FHIRTaskPoller:
    """Simulates polling a FHIR ``Task`` resource for an async Epic extract job.

    A real implementation replaces `poll` with a GET against
    ``{fhir_base_url}/Task/{task_id}`` and reads its ``status`` field.
    """

    transitions: List[FHIRTaskStatus] = field(
        default_factory=lambda: [
            FHIRTaskStatus.REQUESTED,
            FHIRTaskStatus.IN_PROGRESS,
            FHIRTaskStatus.IN_PROGRESS,
            FHIRTaskStatus.COMPLETED,
        ]
    )
    _poll_counts: Dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def poll(self, task_id: str) -> FHIRTaskStatus:
        index = self._poll_counts.get(task_id, 0)
        status = self.transitions[min(index, len(self.transitions) - 1)]
        self._poll_counts[task_id] = index + 1
        return status

    def wait_for_completion(
        self,
        task_id: str,
        max_polls: int = 10,
        poll_interval_seconds: float = 0.0,
    ) -> FHIRTaskStatus:
        for _ in range(max_polls):
            status = self.poll(task_id)
            if status in _TERMINAL_TASK_STATUSES:
                return status
            if poll_interval_seconds:
                time.sleep(poll_interval_seconds)
        raise TimeoutError(
            f"FHIR Task {task_id!r} did not reach a terminal status after {max_polls} polls"
        )


class EpicClient:
    """Simulated Epic ingestion client, wiring Clarity, Caboodle, and FHIR
    Task polling together into one ``fetch_claims`` call."""

    def __init__(
        self,
        clarity_parser: Optional[ClarityExtractParser] = None,
        caboodle_view: Optional[CaboodleStarSchemaView] = None,
        task_poller: Optional[FHIRTaskPoller] = None,
    ):
        self.clarity_parser = clarity_parser or ClarityExtractParser()
        self.caboodle_view = caboodle_view or CaboodleStarSchemaView()
        self.task_poller = task_poller or FHIRTaskPoller()

    def fetch_claims(self, task_id: str = "extract-job-1") -> List[Dict[str, Any]]:
        """Waits for the extract job's FHIR Task to complete, then returns
        Clarity-joined claims annotated with Caboodle drift detection."""
        status = self.task_poller.wait_for_completion(task_id)
        if status != FHIRTaskStatus.COMPLETED:
            raise RuntimeError(f"Epic extract task {task_id!r} ended in status {status.value!r}")

        claims = self.clarity_parser.parse()
        for claim in claims:
            snapshot = self.caboodle_view.current_snapshot(claim["PAT_ENC_CSN_ID"])
            claim["CABOODLE_STAGE_DRIFT"] = bool(
                snapshot is not None and snapshot["WATERFALL_STAGE"] != claim["WATERFALL_STAGE"]
            )
        return claims
