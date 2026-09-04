from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from waterfall_guard.api.app import app
from waterfall_guard.api.dashboard_router import get_supabase_client
from waterfall_guard.api.supabase_client import SupabaseViewClient


class FakeSupabaseViewClient(SupabaseViewClient):
    """Returns canned view rows instead of making a live PostgREST call."""

    def __init__(self, views: Dict[str, List[Dict[str, Any]]]):
        self.views = views

    def fetch_view(self, view_name: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self.views[view_name]


class FailingSupabaseViewClient(SupabaseViewClient):
    """Simulates Supabase being unreachable or misconfigured."""

    def __init__(self):
        pass

    def fetch_view(self, view_name: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        raise RuntimeError("Supabase is unreachable")


@pytest.fixture
def client_factory():
    def _make(fake_client: SupabaseViewClient) -> TestClient:
        app.dependency_overrides[get_supabase_client] = lambda: fake_client
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()


def test_summary_returns_executive_metrics_from_the_view(client_factory):
    fake = FakeSupabaseViewClient(
        {
            "vw_executive_metrics": [
                {
                    "total_claims_analyzed": 42,
                    "total_deadlocked_claims": 3,
                    "total_dollars_at_risk": 15234.50,
                    "avg_resolution_days": 4.5,
                }
            ]
        }
    )

    response = client_factory(fake).get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    assert response.json() == {
        "total_claims_analyzed": 42,
        "total_deadlocked_claims": 3,
        "total_dollars_at_risk": 15234.50,
        "avg_resolution_days": 4.5,
        "pipeline_status": "active",
    }


def test_summary_defaults_to_idle_status_when_the_view_is_empty(client_factory):
    fake = FakeSupabaseViewClient({"vw_executive_metrics": []})

    response = client_factory(fake).get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_status"] == "idle"
    assert body["total_claims_analyzed"] == 0
    assert body["avg_resolution_days"] is None


def test_deadlocks_returns_the_grouped_rule_collision_breakdown(client_factory):
    fake = FakeSupabaseViewClient(
        {
            "vw_deadlock_breakdown": [
                {"deadlock_type": "no_exit_condition", "claim_count": 5, "dollars_at_risk": 9000.0},
                {"deadlock_type": "ambiguous_wq_routing", "claim_count": 2, "dollars_at_risk": 1500.0},
            ]
        }
    )

    response = client_factory(fake).get("/api/v1/dashboard/deadlocks")

    assert response.status_code == 200
    body = response.json()
    assert len(body["deadlocks"]) == 2
    assert body["deadlocks"][0] == {
        "deadlock_type": "no_exit_condition",
        "claim_count": 5,
        "dollars_at_risk": 9000.0,
    }


def test_workqueues_returns_routing_targets_and_dollar_impact(client_factory):
    fake = FakeSupabaseViewClient(
        {
            "vw_workqueue_routing": [
                {"recommended_owner": "Claim Edit WQ - COB Specialist", "claim_count": 4, "dollars_at_risk": 4200.0},
                {"recommended_owner": None, "claim_count": 1, "dollars_at_risk": 87.4},
            ]
        }
    )

    response = client_factory(fake).get("/api/v1/dashboard/workqueues")

    assert response.status_code == 200
    owners = [entry["recommended_owner"] for entry in response.json()["workqueues"]]
    assert owners == ["Claim Edit WQ - COB Specialist", None]


def test_a_supabase_failure_surfaces_as_a_clean_502_not_a_crash(client_factory):
    response = client_factory(FailingSupabaseViewClient()).get("/api/v1/dashboard/summary")

    assert response.status_code == 502
    assert "vw_executive_metrics" in response.json()["detail"]


def test_dashboard_responses_never_leak_phi_shaped_fields(client_factory):
    """The response models are a schema allowlist: even if a view row somehow
    carried a PHI-looking column, response_model serialization strips it."""
    fake = FakeSupabaseViewClient(
        {
            "vw_workqueue_routing": [
                {
                    "recommended_owner": "billing_team",
                    "claim_count": 1,
                    "dollars_at_risk": 100.0,
                    "pat_name": "Doe, Jane",
                }
            ]
        }
    )

    response = client_factory(fake).get("/api/v1/dashboard/workqueues")

    assert "pat_name" not in response.json()["workqueues"][0]
