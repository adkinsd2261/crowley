# V4 Chat Wire RFC — Cognitive Context in Live Prompts

**Status:** Approved for V4.4 implementation (#363–#367)  
**Date:** 2026-07-09  
**Depends on:** V4.2 schema + promotion, V4.3 retrieval caps

---

## Problem

`build_cognitive_context()` serves `/api/cognitive/context` and Actions `cognitive.context`, but [`conversation_runtime.py`](../conversation_runtime.py) `_impl_build_prompt` calls `retrieve_memories()` on legacy `memory_items`. The spec pipeline **retrieval → context → model** is broken at the last hop.

---

## Goal

Wire ranked, sanitized, token-bounded cognitive sections into the chat system prompt without demoting filesystem canon, world truth, or ticket/task authority.

---

## Prompt authority order (fixed)

Top = highest authority. Model must treat lower sections as supporting context only.

| Order | Section | Source today | After V4.4 |
|-------|---------|--------------|------------|
| 1 | Personality + mode + depth | `conversation_runtime.py` | Unchanged |
| 2 | Knowledge files (query-scored) | `load_knowledge_files_context` | Unchanged |
| 3 | Tickets prompt section | `_format_tickets_prompt_section` | Unchanged |
| 4 | Agent activity | `_format_agent_activity_prompt_section` | Unchanged |
| 5 | World context | `get_active_world_context` | Unchanged |
| 6 | Task frame | `_format_task_frame_prompt_section` | Unchanged |
| 7 | Canon memory items | `_format_canon_prompt_section` | Unchanged |
| 8 | **Cognitive memory** | — | **NEW** `## CognitiveMemory` |
| 9 | Legacy hybrid memory (fallback) | `retrieve_memories` block | Only if cognitive empty / cold-start |
| 10 | Open tasks | `list_tasks` | Unchanged |
| 11 | Ground truth footer | `_ground_truth_prompt` | Unchanged |

Cognitive memory **must not** override canon, filesystem docs, or explicit ticket state.

---

## Cognitive block structure (V4.4 #364)

Inside `## CognitiveMemory`:

```
### Current State
- [spark summaries]

### Relevant Decisions
- [decision spark_type rows]

### Recent Activity
- [observation/fact rows]

### Key Constraints
- [patterns + high-confidence constraints]
```

Built by `build_cognitive_context()` → section object → formatter in `conversation_runtime.py`.

The `sections` object is additive for `/api/cognitive/context`; existing
`core_sparks` and `supporting_sparks` compatibility fields stay available for
API/Actions callers until a later breaking-change release.

Raw ranked JSON arrays are **not** pasted into the prompt.

---

## Integration point

### `conversation_runtime._impl_build_prompt`

Pseudocode:

```python
cognitive = build_cognitive_context(
    user_message,
    project_id=active_project_id,
    depth=map_depth_from(classify_response_depth(...)),
    conn=shared_conn_if_available,
)
if cognitive_has_content(cognitive):
    system_parts.append(format_cognitive_memory_section(cognitive))
elif cold_start_fallback_needed(cognitive):
    system_parts.append(format_legacy_memory_fallback(retrieve_memories(...)))
```

### Depth mapping

| Chat `classify_response_depth` | Cognitive `depth` |
|-------------------------------|-------------------|
| brief / light | `light` |
| normal | `medium` |
| deep | `deep` |

---

## Token budget (V4.4 #363)

- Default chat allocation: **~2000 tokens** (conservative char estimate × 1.3)
- The packer receives the caller's remaining prompt budget rather than assuming
  the whole prompt is available for cognitive memory.
- `context_token_budget.pack_sections_to_budget()` trims lowest-score rows first
- Pinned / confirmed sparks protected until single-item cap
- Trace fields (`budget_tokens`, `dropped_count`) logged when `debug=1`; not shown to end user in chat

Count limits from V4.3 (≤15 sparks) apply **before** token packer.

---

## Sanitization

All cognitive text passed through `spark_sanitize.sanitize_cognitive_context_payload()` before prompt formatting — same as API path (T19).

---

## Cold-start fallback (V4.4 #366)

When `context_resolution.count_active_sparks() < COLD_START_ACTIVE_SPARK_THRESHOLD` (10) **or** cognitive sections empty:

1. Include legacy `retrieve_memories()` block
2. Label explicitly: `Supporting memory (legacy fallback — cold start)`
3. Never include both full cognitive block **and** full legacy block with duplicate content

After promotion policy (V4.2 #355) increases active spark count, fallback should rarely trigger.

---

## Security

- Same sensitivity gates as API (`spark_security.filter_ranked_sparks`)
- `depth=light` suppresses high-sensitivity sparks (existing T18 behavior)
- No new external routes; chat path is localhost UI only

---

## Files touched (V4.4)

| File | Change |
|------|--------|
| `context_token_budget.py` | New — budget packer |
| `context_orchestration.py` | Section structure + budget hook |
| `conversation_runtime.py` | Wire cognitive block + fallback tiering |
| `tests/test_prompt_task_frame.py` | Assert cognitive section present |
| `tests/test_chat_api.py` | Integration smoke |
| `tests/test_v4_acceptance_context.py` | Acceptance test 3 |

---

## Non-goals (V4.4)

- Remove `retrieve_memories()` API
- Change `/api/cognitive/context` response shape for external agents (sections additive)
- UI spark browser (V4.5 Actions tools sufficient)

---

## Acceptance

See [V4_ACCEPTANCE_TEST_MATRIX.md](./V4_ACCEPTANCE_TEST_MATRIX.md) test 3: cognitive prompt section stays under token budget with no duplicate legacy dump.
