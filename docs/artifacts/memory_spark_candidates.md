# Memory → Spark Candidate Review (dry-run)

Generated: 2026-07-10T03:50:18.806458+00:00
Scanned: 2506 · Included: 50 · Skipped: 2143

## Include reason counts

- `constraint`: 68
- `decision+importance_4`: 206
- `lesson`: 50
- `pinned+decision+importance_4`: 1
- `pinned+decision+importance_5`: 1
- `pinned+preference+importance_4`: 1
- `pinned+summary`: 1
- `project_update+importance_4`: 10
- `summary`: 25

## Skip reason counts

- `already_linked`: 3
- `duplicate_summary`: 177
- `handoff_receipt`: 425
- `qa_noise`: 1
- `sidequest_noise`: 1
- `status_archived`: 4
- `status_merged`: 1335
- `status_rejected`: 16
- `status_staged`: 57
- `status_stale`: 1
- `too_short`: 11
- `type_excluded`: 112

## Candidates

- #10 [decision] trust=active reason=pinned+decision+importance_5 — Crowley V3.6 Phase 3 dual-writes memories into memory_items QA
- #2 [decision] trust=active reason=pinned+decision+importance_4 — We switched from Qwen to Llama 3.1 8b due to instability
- #2502 [decision] trust=candidate reason=decision+importance_4 — V4.3.1 is now the next ladder before V4.4. Cursor should claim #468 first. V4.4 #363 remains blocked until #472 corpus m
- #2499 [decision] trust=candidate reason=decision+importance_4 — Recovery complete: codebase is back on the clean V4.3 lock baseline. Side-quest changes should be treated as discarded/q
- #2471 [decision] trust=candidate reason=decision+importance_4 — APPROVE #362 PLAN WITH AMENDMENTS. Cursor may implement the V4.3 lock doc, unskip/implement acceptance test 2, update ma
- #2463 [decision] trust=candidate reason=decision+importance_4 — APPROVE #361. Cursor may close #361 and proceed to #362 V4.3 T5 doc lock / clean-retrieval acceptance tests.
- #2457 [decision] trust=candidate reason=decision+importance_4 — DENY #361 RESUBMISSION as E2E-not-clean. This is no longer a #361 code/cap behavior blocker; it is a Crowley workflow pa
- #2453 [decision] trust=candidate reason=decision+importance_4 — DENY #361 until the Actions registry contract regression is fixed. Do not approve or proceed to #362 yet.
- #2448 [decision] trust=candidate reason=decision+importance_4 — APPROVE #361 PLAN WITH REQUIRED AMENDMENTS. The plan is aligned with the V4.3 ladder: default medium cognitive context s
- #2441 [decision] trust=candidate reason=decision+importance_4 — APPROVE #360. The implementation satisfies the approved plan amendments: recall/None scoring parity is tested, invalid q
- #2434 [decision] trust=candidate reason=decision+importance_4 — Do not change lane resolution, secondary-lane filter semantics, W_SPARK_* globals, COGNITIVE_DEPTH_LIMITS, result caps, 
- #2433 [decision] trust=candidate reason=decision+importance_4 — query_mode=None on direct retrieve_sparks must resolve to recall and must not auto-interpret. Invalid non-empty query_mo
- #2432 [decision] trust=candidate reason=decision+importance_4 — Keep score_breakdown compatibility: prefer numeric-only entries in score_breakdown for weights and multipliers. Put prof
- #2431 [decision] trust=candidate reason=decision+importance_4 — Recall profile must be bit-for-bit equivalent to current scoring, including current certainty and secondary-lane behavio
- #2430 [decision] trust=candidate reason=decision+importance_4 — Approve #360 plan for Cursor implementation with amendments.
- #2425 [decision] trust=candidate reason=decision+importance_4 — Cursor may proceed to #360 V4.3 T3 query-mode scoring profiles, one ticket only.
- #2424 [decision] trust=candidate reason=decision+importance_4 — Approve #359 implementation.
- #2416 [decision] trust=candidate reason=decision+importance_4 — Do not change W_SPARK_* base weights, query-mode scoring profiles, result caps, depth limits, chat/build_prompt, legacy 
- #2415 [decision] trust=candidate reason=decision+importance_4 — Secondary lane handling may add a small 1.05 boost only for rows already admitted by the primary lane filter; it must ne
- #2414 [decision] trust=candidate reason=decision+importance_4 — Direct spark_retrieval.retrieve_sparks(query, lanes=None) must not auto-infer lanes in #359.
- #2413 [decision] trust=candidate reason=decision+importance_4 — Lane resolution must be orchestration-owned: explicit lane(s) override inference entirely; inferred lanes apply only whe
- #2412 [decision] trust=candidate reason=decision+importance_4 — Approve #359 plan for Cursor implementation.
- #2407 [decision] trust=candidate reason=decision+importance_4 — Cursor may proceed to #359 V4.3 T2 auto lane inference and pre-score filtering, one ticket only.
- #2406 [decision] trust=candidate reason=decision+importance_4 — Approve #358 implementation.
- #2393 [decision] trust=candidate reason=decision+importance_4 — retrieve_sparks scoring, weights, result caps, and lane filtering behavior must remain unchanged in #358; orchestration-
- #2392 [decision] trust=candidate reason=decision+importance_4 — inferred_lanes must remain a hint only in #358; do not apply lane filters until #359.
- #2391 [decision] trust=candidate reason=decision+importance_4 — Do not add a generic mode= API parameter in T1. If an explicit override is implemented, name it query_mode= to avoid col
- #2390 [decision] trust=candidate reason=decision+importance_4 — T1 must be rules-only. Do not add optional model tie-break hooks beyond a no-op placeholder; no OpenAI/Ollama/Anthropic 
- #2389 [decision] trust=candidate reason=decision+importance_4 — Approve #358 plan for Cursor implementation with amendments.
- #2382 [decision] trust=candidate reason=decision+importance_4 — V4.3 #358+ may proceed next; preserve V4.2 lock and do not weaken V4 acceptance matrix criteria in later doc locks.
- #2381 [decision] trust=candidate reason=decision+importance_4 — Approve #357. V4.2 Input Intelligence is locked from Codex QA perspective.
- #2373 [decision] trust=candidate reason=decision+importance_4 — Deny #357 pending matrix restoration and V4.2 acceptance coverage fix.
- #2365 [decision] trust=candidate reason=decision+importance_4 — crowley.py remains V4.1 facade/version 4.1.0; no monolith regression observed.
- #2364 [decision] trust=candidate reason=decision+importance_4 — T5 guardrails satisfied: CROWLEY_TEST_MODE fixture path preserved, 1-retry-then-discard preserved, cache stores only suc
- #2363 [decision] trust=candidate reason=decision+importance_4 — Approve Cursor implementation for #356.
- #2354 [decision] trust=candidate reason=decision+importance_4 — Canonicalization must be applied only after validation/defaulting and before cache store/return, including empty-array s
- #2353 [decision] trust=candidate reason=decision+importance_4 — Keep crowley.py change to the narrow _call_openai temperature passthrough only; no facade expansion or monolith regressi
- #2352 [decision] trust=candidate reason=decision+importance_4 — Keep durable SQLite extraction cache out of initial T5 unless explicitly re-approved; ship in-memory process cache only 
- #2351 [decision] trust=candidate reason=decision+importance_4 — Approve #356 plan for Cursor implementation.
- #2348 [decision] trust=candidate reason=decision+importance_4 — None; short planning update only.
- #2345 [decision] trust=candidate reason=decision+importance_4 — V4.6 Explore Activation: mint only after #374; ephemeral clusters only (no Concept table); precise default parallel expl
- #2343 [decision] trust=candidate reason=decision+importance_4 — No new product decisions recorded.
- #2338 [decision] trust=candidate reason=decision+importance_4 — T4 promotion policy guardrails are acceptable: auto promotion requires normal sensitivity, candidate state, confirmed ce
- #2337 [decision] trust=candidate reason=decision+importance_4 — Previous blocker #2324 is resolved: facade/version tests now pass and crowley.py is not the old monolith.
- #2336 [decision] trust=candidate reason=decision+importance_4 — Approved Cursor's #355 fix.
- #2323 [decision] trust=candidate reason=decision+importance_4 — Denied pending fix: #355 cannot be approved while V4.1 facade extraction/version lock is broken. Do not treat version/fa
- #2301 [decision] trust=candidate reason=decision+importance_4 — Ship parser before ingest (#78).
- #2295 [decision] trust=candidate reason=decision+importance_4 — Approved #355 plan with guardrails: auto-promotion requires candidate + confirmed + normal sensitivity + confidence gate
- #2290 [decision] trust=candidate reason=decision+importance_4 — Approved #354: long mixed input chunks before temporary/noise decisions; one temporary/noise chunk does not discard usef
- #2273 [decision] trust=candidate reason=decision+importance_4 — Approved T3 plan v2: one temporary/noise section must not discard useful chunks from the same receipt; short-input T1 be
