from datetime import datetime, timedelta, timezone

from waterfall_guard.agents.reconciliation_agent import ReconciliationAgent
from waterfall_guard.models.claim import Claim, ClaimStatus


def make_claim(status: ClaimStatus, days_since_update: int) -> Claim:
    now = datetime.now(timezone.utc)
    return Claim(
        claim_id="C-1",
        patient_id="P-1",
        payer="Acme Payer",
        status=status,
        amount=100.0,
        submitted_at=now - timedelta(days=days_since_update + 1),
        last_status_change_at=now - timedelta(days=days_since_update),
    )


def test_flags_stalled_claim_past_threshold():
    agent = ReconciliationAgent(orphan_threshold_days=14)
    claim = make_claim(ClaimStatus.SUBMITTED, days_since_update=20)

    orphaned = agent.find_orphaned_claims([claim])

    assert len(orphaned) == 1
    assert orphaned[0].claim.claim_id == "C-1"


def test_does_not_flag_recent_claim():
    agent = ReconciliationAgent(orphan_threshold_days=14)
    claim = make_claim(ClaimStatus.SUBMITTED, days_since_update=5)

    assert agent.find_orphaned_claims([claim]) == []


def test_does_not_flag_terminal_status():
    agent = ReconciliationAgent(orphan_threshold_days=14)
    claim = make_claim(ClaimStatus.PAID, days_since_update=30)

    assert agent.find_orphaned_claims([claim]) == []
