# V4 Acceptance Test Matrix

**Status:** Planning lock — fixtures and pass criteria defined; implementation gates V4.2–V4.5 doc-lock tickets  
**Date:** 2026-07-09  
**Spec source:** ChatGPT V4 cognitive acceptance tests (6)

---

## Overview

Each acceptance test maps to a pytest module, JSON fixture(s), implementing ticket(s), and explicit pass criteria. Tests may `@unittest.skip` until their ladder lands; each ladder doc-lock ticket must unskip and implement its own acceptance module before claiming done. The matrix is the contract for V4.5 T6 (#374) full suite.

| # | Spec name | Fixture(s) | Test module | Ticket gate | Status |
|---|-----------|------------|-------------|-------------|--------|
| 1 | Messy input handling | `messy_multi_domain_input.json` | `test_v4_acceptance_input.py` | V4.2 #357 | **Pass** (V4.2 lock) |
| 2 | Clean retrieval | `retrieval_finance_query.json` | `test_v4_acceptance_retrieval.py` | V4.3 #362 | **Pass** (V4.3 lock) |
| 3 | Context control | `context_token_budget.json` | `test_v4_acceptance_context.py` | V4.4 #367 | Pending |
| 4 | State evolution | `truth_state_evolution.json` | `test_v4_acceptance_truth.py` | V4.5 #374 | Pending |
| 5 | Noise resistance | `noise_ignore_temporary.json` | `test_v4_acceptance_input.py` | V4.2 #357 | **Pass** (V4.2 lock) |
| 6 | Security validation | `security_no_leak.json` | `test_v4_acceptance_security.py` | V4.5 #374 | Pending |

Meta validation (always runs): `test_v4_acceptance_matrix.py` — fixture schema + matrix completeness.

---

## Test 1 — Messy input handling

**Spec:** System correctly splits and structures multi-domain input.

**Fixture:** `tests/fixtures/v4_acceptance/messy_multi_domain_input.json`

**Setup:**

1. Ingest `raw_text` via `POST /api/cognitive/ingest?sync=1`
2. Use `CROWLEY_TEST_MODE=1` with extraction fixture override per chunk

**Pass criteria:**

- ≥2 sparks persisted with distinct `lane` values from {money, health, work}
- Each spark passes `validate_spark()`
- Same receipt `memory_item_id` in lineage for all sparks from one ingest
- No spark content exceeds 300 chars
- Temporary/noise sections do not cause useful sections from the same raw input
  to be discarded

**Fail if:**

- Single catch-all summary spark only
- Cross-lane contamination in one spark (finance + health in same content without boundary)

---

## Test 2 — Clean retrieval

**Spec:** Returns correct domain-specific answers without noise.

**Fixture:** `tests/fixtures/v4_acceptance/retrieval_finance_query.json`

**Setup:**

1. Seed sparks from fixture `seed_sparks` via maintenance seed or direct insert
   (includes money + health lanes)
2. Query cognitive context with `q=<finance_query>` and **no** explicit `lane=` /
   `lanes=` so V4.3 auto lane inference applies (primary path). Explicit
   `lane=money` remains a supported override but is not the acceptance primary.

**Pass criteria:**

- `trace.lane_source` is `inferred` and `trace.lanes_used` is `["money"]` (or
  equivalent sorted money-only list)
- All returned core/supporting sparks have `lane=money`
- No health-lane spark in top 15 results
- `trace.retrieved_count` ≤ 15 (V4.3 cap)
- `trace.truncated_count` is present (integer ≥ 0)
- Cross-domain queries may infer multiple lanes; single-domain finance queries
  must not pull health-lane sparks

**Fail if:**

- Health or unrelated lane spark appears in core set
- Overflow beyond cap without `truncated_count` in trace
- Explicit `lane=` required for the finance fixture to exclude health

---

## Test 3 — Context control

**Spec:** Never exceeds token limits; no overloading.

**Fixture:** `tests/fixtures/v4_acceptance/context_token_budget.json`

**Setup:**

1. Seed `many_sparks` count (20+) in one lane
2. Build prompt via `build_prompt(query)` or cognitive context with chat budget

**Pass criteria:**

- Cognitive memory section char length ≤ `max_prompt_chars` from fixture (default 8000 conservative)
- `trace.dropped_count` > 0 when seed exceeds budget
- No raw JSON dump of full retrieval array in system prompt
- `/api/cognitive/context` keeps compatibility fields while adding structured
  sections

**Fail if:**

- Prompt contains unbounded spark list
- Token/char estimate exceeds budget without trimming

---

## Test 4 — State evolution

**Spec:** Updates truth correctly over time.

**Fixture:** `tests/fixtures/v4_acceptance/truth_state_evolution.json`

**Setup:**

1. Insert `initial_spark` (tentative, old fact)
2. Ingest `correcting_spark` (confirmed, contradicts)
3. Run conflict resolution / correction API

**Pass criteria:**

- Older spark `certainty` downgraded or `trust_state` → stale/rejected
- Newer confirmed spark ranks higher in retrieval
- No hard DELETE of older row

**Fail if:**

- Both sparks present as equally authoritative with no lineage event
- Older spark unchanged after explicit contradiction ingest

---

## Test 5 — Noise resistance

**Spec:** Ignores irrelevant or temporary input.

**Fixture:** `tests/fixtures/v4_acceptance/noise_ignore_temporary.json`

**Setup:**

1. Ingest each item in `inputs[]` with intent classifier enabled

**Pass criteria:**

- `ignore` inputs: 0 new sparks
- `temporary` inputs: 0 active sparks (ephemeral or tagged non-retained)
- `store` input: ≥1 spark

**Fail if:**

- Filler/greeting text creates active sparks
- Temporary note appears in retrieval for unrelated query

---

## Test 6 — Security validation

**Spec:** No sensitive data leaks or improper storage.

**Fixture:** `tests/fixtures/v4_acceptance/security_no_leak.json`

**Setup:**

1. Attempt ingest of `blocked_content` (sk- token, Bearer, instructions)
2. Request context with `depth=light` for high-sensitivity seed

**Pass criteria:**

- Ingest rejects or redacts blocked content (T20)
- `sensitivity=high` spark excluded from light-depth context (T18)
- Sanitized context has no raw `sk-` or `Bearer` substrings
- Encrypted rows (post-V4.5): `content` column empty or ciphertext; plaintext only via authorized decrypt
- Encryption design doc covers key loss, plaintext/embedding behavior, tamper
  detection, and restore/recovery limits before storage behavior changes

**Fail if:**

- Secret pattern persisted verbatim in sparks.content
- High-sensitivity spark returned in light depth context

---

## V4.5 full suite (#374)

`tests/test_v4_acceptance_full.py` imports or re-runs all six tests in one gate:

```bash
CROWLEY_TEST_MODE=1 CROWLEY_EMBED_PROVIDER=off python -m unittest \
  tests.test_v4_acceptance_matrix \
  tests.test_v4_acceptance_input \
  tests.test_v4_acceptance_retrieval \
  tests.test_v4_acceptance_context \
  tests.test_v4_acceptance_truth \
  tests.test_v4_acceptance_security \
  tests.test_v4_acceptance_full \
  -v
```

Green suite + `docs/V4_COGNITIVE_COMPLETION_LOCK.md` = V4 cognitive complete, V5 automation may be planned.

---

## Fixture index

| File | Purpose |
|------|---------|
| `messy_multi_domain_input.json` | Test 1 raw ingest |
| `noise_ignore_temporary.json` | Test 5 intent cases |
| `retrieval_finance_query.json` | Test 2 seeds + query |
| `context_token_budget.json` | Test 3 overflow seeds |
| `truth_state_evolution.json` | Test 4 contradiction pair |
| `security_no_leak.json` | Test 6 blocked + sensitive seeds |
| `matrix_manifest.json` | Machine-readable index for meta test |
