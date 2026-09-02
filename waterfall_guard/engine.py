"""Rule-vs-Waterfall Reconciliation Engine.

Reconciles a de-identified claim against Epic's native revenue-cycle
waterfall and a hospital's custom rule set (hold conditions, secondary
work-queue gates), and flags claims stuck in a deadlock: no path forward,
ambiguous routing, or a queue with nobody accountable for escalation.

Everything this module touches is de-identified state/rule metadata (see
``deident.py``) — no PHI ever reaches here, so its output is safe to hand to
an external Zero-Data-Retention (ZDR) LLM call for narrative diagnosis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class WaterfallStage(str, Enum):
    """Epic's native revenue-cycle waterfall, in traversal order."""

    CHARGE_ROUTER_REVIEW = "charge_router_review"
    CHARGE_REVIEW = "charge_review"
    CLAIM_EDIT = "claim_edit"
    FOLLOW_UP = "follow_up"
    ACCOUNT = "account"
    CREDIT_ADJUSTMENT = "credit_adjustment"


STAGE_ORDER: List[WaterfallStage] = [
    WaterfallStage.CHARGE_ROUTER_REVIEW,
    WaterfallStage.CHARGE_REVIEW,
    WaterfallStage.CLAIM_EDIT,
    WaterfallStage.FOLLOW_UP,
    WaterfallStage.ACCOUNT,
    WaterfallStage.CREDIT_ADJUSTMENT,
]


def next_stage(stage: WaterfallStage) -> Optional[WaterfallStage]:
    """The stage a claim advances to next, or None if `stage` is terminal."""
    index = STAGE_ORDER.index(stage)
    if index + 1 == len(STAGE_ORDER):
        return None
    return STAGE_ORDER[index + 1]


def is_terminal(stage: WaterfallStage) -> bool:
    return stage == STAGE_ORDER[-1]


DEFAULT_STALL_THRESHOLD_DAYS = 14


@dataclass
class HoldCondition:
    """A hospital-defined rule that can keep a claim from exiting its stage.

    Data-driven so a hospital's actual rule set can be ingested from
    JSON/config (see `HospitalRuleSet.from_config`) rather than hardcoded.
    """

    name: str
    stage: WaterfallStage
    trigger_field: str
    trigger_equals: Any = None
    trigger_present: bool = False
    resolves_via_wq: Optional[str] = None

    def applies_to(self, record: Dict[str, Any]) -> bool:
        if record.get("waterfall_stage") != self.stage.value:
            return False
        value = record.get(self.trigger_field)
        if self.trigger_present:
            return bool(value)
        if self.trigger_equals is not None:
            return value == self.trigger_equals
        return False


@dataclass
class WQGate:
    """A secondary work queue a claim must clear to advance past a stage."""

    wq_id: str
    stage: WaterfallStage
    owner: Optional[str] = None
    escalation_owner: Optional[str] = None


@dataclass
class HospitalRuleSet:
    hold_conditions: List[HoldCondition] = field(default_factory=list)
    wq_gates: Dict[str, WQGate] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "HospitalRuleSet":
        """Build a rule set from a plain dict (as loaded from a hospital's JSON config)."""
        hold_conditions = [
            HoldCondition(
                name=hold["name"],
                stage=WaterfallStage(hold["stage"]),
                trigger_field=hold["trigger_field"],
                trigger_equals=hold.get("trigger_equals"),
                trigger_present=hold.get("trigger_present", False),
                resolves_via_wq=hold.get("resolves_via_wq"),
            )
            for hold in config.get("hold_conditions", [])
        ]
        wq_gates = {
            gate["wq_id"]: WQGate(
                wq_id=gate["wq_id"],
                stage=WaterfallStage(gate["stage"]),
                owner=gate.get("owner"),
                escalation_owner=gate.get("escalation_owner"),
            )
            for gate in config.get("wq_gates", [])
        }
        return cls(hold_conditions=hold_conditions, wq_gates=wq_gates)


@dataclass
class DeadlockFinding:
    token_id: str
    stage: WaterfallStage
    deadlock_types: List[str]
    active_hold_names: List[str]
    eligible_wq_ids: List[str]
    unassigned_wq_ids: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "stage": self.stage.value,
            "deadlock_types": self.deadlock_types,
            "active_hold_names": self.active_hold_names,
            "eligible_wq_ids": self.eligible_wq_ids,
            "unassigned_wq_ids": self.unassigned_wq_ids,
        }


class ReconciliationEngine:
    """Diagnoses deadlocks by reconciling a claim's state against the rule set."""

    def __init__(
        self,
        rules: HospitalRuleSet,
        stall_threshold_days: int = DEFAULT_STALL_THRESHOLD_DAYS,
    ):
        self.rules = rules
        self.stall_threshold_days = stall_threshold_days

    def _active_holds(self, record: Dict[str, Any]) -> List[HoldCondition]:
        return [hold for hold in self.rules.hold_conditions if hold.applies_to(record)]

    def diagnose(self, record: Dict[str, Any]) -> Optional[DeadlockFinding]:
        stage = WaterfallStage(record["waterfall_stage"])
        if is_terminal(stage):
            # Nothing follows credit/adjustment: the claim has exited the
            # waterfall, so it cannot be deadlocked.
            return None

        active_holds = self._active_holds(record)
        eligible_wq_ids: List[str] = record.get("eligible_wq_ids") or []
        deadlock_types: List[str] = []

        # 1. No exit condition: an active hold with no WQ path defined (or
        #    routed to a WQ that isn't a known gate) that could ever clear it.
        unresolvable_holds = [
            hold
            for hold in active_holds
            if hold.resolves_via_wq is None or hold.resolves_via_wq not in self.rules.wq_gates
        ]
        if unresolvable_holds:
            deadlock_types.append("no_exit_condition")

        # 2. Ambiguous routing: the claim qualifies for more than one WQ and
        #    every one of them is unassigned, so nobody actually owns it.
        unassigned_wq_ids = [
            wq_id
            for wq_id in eligible_wq_ids
            if wq_id in self.rules.wq_gates and self.rules.wq_gates[wq_id].owner is None
        ]
        if len(eligible_wq_ids) > 1 and len(unassigned_wq_ids) == len(eligible_wq_ids):
            deadlock_types.append("ambiguous_wq_routing")

        # 3. Sitting in a queue with no escalation owner while actively held
        #    or stalled well past the normal dwell time for a stage.
        current_wq_id = record.get("current_wq_id")
        current_gate = self.rules.wq_gates.get(current_wq_id) if current_wq_id else None
        is_stalled = record.get("days_in_stage", 0) >= self.stall_threshold_days
        if current_gate is not None and current_gate.escalation_owner is None and (active_holds or is_stalled):
            deadlock_types.append("no_escalation_owner")

        if not deadlock_types:
            return None

        return DeadlockFinding(
            token_id=record["token_id"],
            stage=stage,
            deadlock_types=deadlock_types,
            active_hold_names=[hold.name for hold in active_holds],
            eligible_wq_ids=eligible_wq_ids,
            unassigned_wq_ids=unassigned_wq_ids,
        )

    def diagnose_batch(self, records: List[Dict[str, Any]]) -> List[DeadlockFinding]:
        findings = (self.diagnose(record) for record in records)
        return [finding for finding in findings if finding is not None]

    def build_zdr_payload(self, findings: List[DeadlockFinding]) -> Dict[str, Any]:
        """Structured diagnostic payload, safe to send to a Zero-Data-Retention LLM.

        Contains only tokens (non-PHI) and rule/state metadata — no raw
        patient data ever passes through this method.
        """
        return {
            "schema": "waterfall_guard.deadlock_diagnosis.v1",
            "finding_count": len(findings),
            "findings": [finding.as_dict() for finding in findings],
        }
