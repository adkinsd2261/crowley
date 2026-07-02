# Crowley V3.9.5 + V3.9.6 -- Pre-V4 Quality Plan

**Status:** Complete — V3.9.5 + V3.9.6 shipped (2026-07-02); followed by **V3.9.7 Experience & Reliability** (#40–#49)
**Baseline:** V3.9.7 (`Crowley V3.9.7 Workspace Experience & Reliability`)
**Owner model:** Mr. Go sets intent; Codex plans and reviews; Cursor implements; Crowley stores truth.

---

## 1. Summary

Ship two small releases before V4 connectivity:

1. **V3.9.5 -- Conversation + Model Behavior**
   Make Crowley feel like the project co-founder by default, with inferred response modes so status and debug answers stay concise while exploration can breathe.
2. **V3.9.6 -- Workspace Polish**
   Make the browser workspace livable for daily use by tightening loading, error, empty, streaming, navigation, and "what changed" flow.

V4 connectivity is the next initiative. Later pre-V4 gates are captured in [PRE_V4_FUTURE_RELEASE_LADDER.md](./PRE_V4_FUTURE_RELEASE_LADDER.md) and should not be ticketed until V4 planning begins.

---

## 2. Guiding principle

Crowley should feel easy to talk to every day, but still be inspectable when work gets serious.

That means:

- No visible conversation-mode toggle yet.
- Prompt behavior should be inferred from the user's phrasing.
- Diagnostics stay factual and SQL-first.
- UI polish favors dead-state removal and flow over a redesign.
- Cursor receives small tickets that can ship in one focused pass.

---

## 3. Release ladder

| Release | Goal | Ticket range |
|---------|------|--------------|
| V3.9.5 Conversation + Model Behavior | Make Crowley pleasant, mode-aware, and correctly terse/deep | #25-#30 ✅ |
| V3.9.6 Workspace Polish | Make the browser workspace livable for a week of real use | #31-#36 |
| V3.9.7-V3.9.9 Future Gates | Memory freshness, work intelligence, operator preflight | Planning reserve |
| V4 Connectivity | External collectors and multi-project behavior | After pre-V4 gates ship or are intentionally skipped |

Ticket IDs assume this packet is minted after V3.9.4/#24.

---

## 4. V3.9.5 -- Conversation + Model Behavior

**Status:** Shipped (2026-07-02) · Tickets `#25–#30` · Spec: [V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md](./V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md)

**Goal:** make Crowley pleasant to talk to daily.

Cursor ticket slices:

1. Add deterministic conversation mode classifier.
   - Modes: `status`, `planning`, `exploration`, `debug`, `diagnostics`, `bug`, `casual`.
   - Prompt includes detected mode and expected answer shape.
2. Add response depth controller.
   - Depths: `brief`, `standard`, `deep`.
   - Default `standard`; `deep` for planning/exploration; `brief` for status/check/update asks.
3. Trim personality prompt toward co-founder voice.
   - Warm, opinionated, useful, less theatrical.
   - Keep "Crowley is the running system" identity.
4. Separate diagnostics tone from chat tone.
   - Diagnostics remains factual, structured, and SQL/fact-first.
5. Add deterministic model-behavior regression fixtures.
   - Test prompt/controller behavior, not live model quality.
6. Sweep confirmed chat UX bugs only.
   - Empty/model-error states, slash-command rejection clarity, streaming completion/error handling.

Done when Mr. Go prefers Crowley over a raw model chat for project work.

---

## 5. V3.9.6 -- Workspace Polish

**Goal:** make the workspace livable.

Cursor ticket slices:

1. Add consistent loading, error, and empty states.
   - Chat, panels, ticket detail, Agent Feed, Memory, diagnostics.
2. Smooth chat streaming states.
   - Clear start, token flow, completion, and error behavior.
3. Tighten navigation and panel flow.
   - Predictable Intelligence tabs; ticket detail should not flicker unnecessarily.
4. Add a clear "what changed" feed.
   - Use existing agent activity, ticket events, and handoff data.
5. Run a frontend livability pass.
   - Spacing, overflow, mobile-ish widths, dead affordances.
6. Final docs and version lock.
   - Add release docs, update current-state docs, and lock V4 start conditions.

Done when Crowley can be used for a week without the frontend feeling half broken.

---

## 6. V4 readiness gate

Do not begin V4 connectivity until these are true:

- V3.9.5 prompt/controller behavior is deterministic and covered by tests. ✅
- Quick status/check/update asks are brief by default. ✅
- Planning and exploration asks can become deep without a manual toggle. ✅
- Diagnostics tone is separate from chat tone. ✅
- Confirmed chat UX bugs are fixed without feature creep. ✅
- Workspace panels have loading/error/empty states. ✅
- Recent Cursor/Codex changes are obvious from the browser. ✅
- V3.9.5 and V3.9.6 docs are current. ✅ (locked 2026-07-02)
- Full regression suite passes. ✅ (**147 tests**)

---

## 7. Test plan

- Focused prompt/controller tests for V3.9.5.
- Focused UI/static tests for V3.9.6.
- Regression: `python -m unittest discover -s tests -q`.
- Manual QA:
  - Ask for a quick status update.
  - Ask for deep planning thoughts.
  - Trigger diagnostics.
  - Exercise a chat empty/model-error case where feasible.
  - Use Tickets, Agent Feed, Memory, and "what changed" surfaces in the browser.

---

## 8. Assumptions

- Crowley stays local-first and SQLite-backed.
- Inferred modes only for now; no manual mode toggle.
- Crowley's default chat persona is "project co-founder," not terse operator.
- V3.9.6 prioritizes states and flow over visual redesign.
- No V4 collectors or multi-project implementation until these two releases are done.
- Cursor ships ticket slices; Codex reviews each before approval.
