from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ClaimStatus(str, Enum):
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    IN_ADJUDICATION = "in_adjudication"
    PAID = "paid"
    DENIED = "denied"
    REJECTED = "rejected"


class Claim(BaseModel):
    claim_id: str
    patient_id: str
    payer: str
    status: ClaimStatus
    amount: float
    submitted_at: datetime
    last_status_change_at: datetime
    expected_response_by: Optional[datetime] = None
