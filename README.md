# waterfall-guard

AI-driven state-reconciliation agent for diagnosing orphaned revenue cycle claims in Epic EHRs.

## What it does

`waterfall-guard` diagnoses claims that get stuck mid-cycle in Epic's revenue
cycle waterfall (Charge Router Review -> Charge Review -> Claim Edit ->
Follow-up -> Account -> Credit/Adjustment). The pipeline:

1. **`deident.py`** ingests a raw Epic extract (`PAT_ENC_CSN_ID`, patient
   demographics, balances, WQ IDs) and tokenizes every PHI-bearing field with
   a salted HMAC, entirely in local memory. What comes out is a de-identified
   payload of non-PHI state and rule metadata plus a correlation token; the
   token -> raw-value mapping never leaves the process and is only reversed
   locally via the vault's `reidentify` method.
2. **`engine.py`** (the Rule-vs-Waterfall Reconciliation Engine) reconciles
   each de-identified claim against the native waterfall stages and a
   hospital's custom rules (hold conditions, secondary WQ gates), and flags
   deadlocks: claims with **no exit condition** (an active hold nothing can
   clear), **ambiguous WQ routing** (eligible for multiple work queues, all
   unowned), or sitting in a queue with **no escalation owner** while stalled.
   It emits a structured, PHI-free diagnostic payload ready for a
   Zero-Data-Retention (ZDR) LLM call.
3. **`main.py`** wires the two together end-to-end: raw claim data ->
   `deident.py` -> `engine.py` -> deadlock diagnosis payload. Run it with
   `python -m waterfall_guard.main` to see a worked simulation.

## Project layout

```
waterfall_guard/
  deident.py           local PHI tokenization / re-identification vault
  engine.py             waterfall stages, hospital rules, deadlock detection
  agents/               legacy orphaned-claim reconciliation agent
  integrations/         Epic FHIR client
  models/               claim data models
  config/               environment-driven settings
  main.py                wires deident.py -> engine.py into one simulation
tests/                    unit tests
```

## Setup

```
pip install -r requirements.txt
cp .env.example .env   # fill in Epic FHIR credentials
python -m waterfall_guard.main
```

## Status

`deident.py` and `engine.py` implement the core de-identification and
deadlock-detection logic against a synthetic sample claim set in `main.py`.
`EpicClient.fetch_claims` is still a stub — implement the real FHIR
`Claim`/`ClaimResponse` search once Epic sandbox credentials are available,
and feed its output into `Deidentifier.deidentify_batch` in place of
`RAW_CLAIMS`.
