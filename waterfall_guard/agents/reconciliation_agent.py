from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from waterfall_guard.config.settings import settings
from waterfall_guard.models.claim import Claim, ClaimStatus

TERMINAL_STATUSES = {ClaimStatus.PAID, ClaimStatus.DENIED, ClaimStatus.REJECTED}


@dataclass
class OrphanedClaim:
    claim: Claim
    days_stalled: int
    reason: str


class ReconciliationAgent:
    """Flags claims stuck mid-cycle with no recent state change."""

    def __init__(self, orphan_threshold_days: int | None = None):
        self.orphan_threshold_days = (
            orphan_threshold_days
            if orphan_threshold_days is not None
            else settings.orphan_threshold_days
        )

    def find_orphaned_claims(self, claims: List[Claim]) -> List[OrphanedClaim]:
        now = datetime.now(timezone.utc)
        orphaned = []
        for claim in claims:
            if claim.status in TERMINAL_STATUSES:
                continue

            days_stalled = (now - claim.last_status_change_at).days
            if days_stalled < self.orphan_threshold_days:
                continue

            reason = f"no status change for {days_stalled} days (status={claim.status.value})"
            orphaned.append(
                OrphanedClaim(claim=claim, days_stalled=days_stalled, reason=reason)
            )

        return orphaned
