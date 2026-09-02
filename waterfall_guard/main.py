from waterfall_guard.agents.reconciliation_agent import ReconciliationAgent
from waterfall_guard.integrations.epic_client import EpicClient


def run() -> None:
    client = EpicClient()
    claims = client.fetch_claims()

    agent = ReconciliationAgent()
    orphaned = agent.find_orphaned_claims(claims)

    if not orphaned:
        print("No orphaned claims found.")
        return

    print(f"{len(orphaned)} orphaned claim(s) found:")
    for entry in orphaned:
        print(f"  - {entry.claim.claim_id}: {entry.reason}")


if __name__ == "__main__":
    run()
