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
3. **`integrations/epic_client.py`** ingests claims from Epic: a mock
   **Clarity** SQL extract (relational tables joined on `PAT_ENC_CSN_ID`), a
   mock **Caboodle** star-schema view (`IsCurrent`-flagged dimension rows,
   which can lag Clarity's live state — the client flags that drift), and a
   **FHIR `Task`** polling simulation for the async extract job.
4. **`llm/client.py`** sends the engine's diagnostic payload to an LLM under
   an enforced **Zero-Data-Retention (ZDR)** configuration (`store: false`
   plus any HIPAA/BAA-compliance headers a provider requires), with a
   structured prompt asking it to diagnose the root-cause rule collision and
   propose a routing fix and a recommended owner. Falls back to a
   structured error result — never raises — if the call fails or times out.
5. **`main.py`** wires all of the above end-to-end: Epic ingestion ->
   `deident.py` -> `engine.py` -> `llm/client.py` -> a routing-fix diagnosis.
   Run it with `python -m waterfall_guard.main` to see a worked simulation
   (using an offline demo transport in place of a real LLM call).

## Project layout

```
waterfall_guard/
  deident.py             local PHI tokenization / re-identification vault
  engine.py               waterfall stages, hospital rules, deadlock detection
  llm/client.py            ZDR-enforced LLM diagnostic client
  agents/                 legacy orphaned-claim reconciliation agent
  integrations/           mock Clarity/Caboodle/FHIR Task Epic ingestion
  models/                 claim data models
  config/                 environment-driven settings
  main.py                  wires ingestion -> deident -> engine -> llm
tests/                      unit tests
```

## Setup

```
pip install -r requirements.txt
cp .env.example .env   # fill in Epic FHIR credentials
python -m waterfall_guard.main
```

## Status

`deident.py`, `engine.py`, `integrations/epic_client.py`, and `llm/client.py`
implement the full pipeline against mock Clarity/Caboodle data in
`epic_client.py` and an offline demo transport in `main.py`. Still to wire up
for production: real Epic FHIR/Clarity/Caboodle credentials in
`epic_client.py`, and a real ZDR-compliant LLM transport in place of
`main.py`'s `_offline_demo_transport`.
