"""Phase 2 Executive Reporting API.

Every endpoint here reads exclusively from the de-identified Supabase
dashboard views created in ``scripts/02_create_dashboard_views.sql``
(``vw_executive_metrics``, ``vw_deadlock_breakdown``,
``vw_workqueue_routing``). Those views aggregate over
``deadlock_diagnostics``/``pipeline_runs``, which only ever store
de-identified tokens and rule/state metadata (see ``deident.py``,
``engine.py``) - never raw PHI.

Each response is also typed with a Pydantic model naming exactly the
fields a dashboard needs. That is a second line of defense, not just
documentation: if a view ever grew a PHI-shaped column by mistake,
FastAPI's response-model serialization drops any field the model doesn't
declare, so it could never reach a client through this router.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from waterfall_guard.api.supabase_client import SupabaseViewClient

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


class ExecutiveSummary(BaseModel):
    total_claims_analyzed: int = 0
    total_deadlocked_claims: int = 0
    total_dollars_at_risk: float = 0.0
    avg_resolution_days: Optional[float] = None
    pipeline_status: str


class DeadlockBreakdownEntry(BaseModel):
    deadlock_type: str
    claim_count: int
    dollars_at_risk: float


class DeadlockBreakdownResponse(BaseModel):
    deadlocks: List[DeadlockBreakdownEntry]


class WorkqueueRoutingEntry(BaseModel):
    recommended_owner: Optional[str] = None
    claim_count: int
    dollars_at_risk: float


class WorkqueueRoutingResponse(BaseModel):
    workqueues: List[WorkqueueRoutingEntry]


def get_supabase_client() -> SupabaseViewClient:
    return SupabaseViewClient()


def _fetch_view_or_502(client: SupabaseViewClient, view_name: str) -> List[Dict[str, Any]]:
    try:
        return client.fetch_view(view_name)
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean 502, never a stack trace
        raise HTTPException(status_code=502, detail=f"Failed to read {view_name}: {exc}") from exc


@router.get("/summary", response_model=ExecutiveSummary)
def get_summary(client: SupabaseViewClient = Depends(get_supabase_client)) -> ExecutiveSummary:
    """Global AR at risk, deadlock counts, and active pipeline status."""
    rows = _fetch_view_or_502(client, "vw_executive_metrics")
    metrics = rows[0] if rows else {}
    claims_analyzed = metrics.get("total_claims_analyzed") or 0

    return ExecutiveSummary(
        total_claims_analyzed=claims_analyzed,
        total_deadlocked_claims=metrics.get("total_deadlocked_claims") or 0,
        total_dollars_at_risk=metrics.get("total_dollars_at_risk") or 0.0,
        avg_resolution_days=metrics.get("avg_resolution_days"),
        pipeline_status="active" if claims_analyzed else "idle",
    )


@router.get("/deadlocks", response_model=DeadlockBreakdownResponse)
def get_deadlocks(client: SupabaseViewClient = Depends(get_supabase_client)) -> DeadlockBreakdownResponse:
    """Grouped breakdown of rule collisions and their dollar impact."""
    rows = _fetch_view_or_502(client, "vw_deadlock_breakdown")
    return DeadlockBreakdownResponse(deadlocks=rows)


@router.get("/workqueues", response_model=WorkqueueRoutingResponse)
def get_workqueues(client: SupabaseViewClient = Depends(get_supabase_client)) -> WorkqueueRoutingResponse:
    """Assigned work-queue routing targets and their at-risk dollar totals."""
    rows = _fetch_view_or_502(client, "vw_workqueue_routing")
    return WorkqueueRoutingResponse(workqueues=rows)
