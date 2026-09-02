# waterfall-guard

AI-driven state-reconciliation agent for diagnosing orphaned revenue cycle claims in Epic EHRs.

## What it does

`waterfall-guard` pulls claims from Epic (via its FHIR R4 API) and flags claims
that have stalled mid-cycle — submitted or acknowledged but with no status
change for longer than an expected window — so revenue cycle staff can
investigate before the claim ages out.

## Project layout

```
waterfall_guard/
  agents/            reconciliation logic
  integrations/       Epic FHIR client
  models/             claim data models
  config/             environment-driven settings
  main.py             CLI entry point
tests/                 unit tests
```

## Setup

```
pip install -r requirements.txt
cp .env.example .env   # fill in Epic FHIR credentials
python -m waterfall_guard.main
```

## Status

Early scaffold. `EpicClient.fetch_claims` is a stub — implement the real FHIR
`Claim`/`ClaimResponse` search once Epic sandbox credentials are available.
