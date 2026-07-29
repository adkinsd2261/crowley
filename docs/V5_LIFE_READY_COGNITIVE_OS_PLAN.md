# Crowley V5 — Life-Ready Cognitive OS + Project Forge

**Document type:** Repository-grounded north-star and release plan
**Status:** Approved by Mr. Go on 2026-07-28 — release packets remain separately reviewable
**Baseline:** `main` at `ab04924189cde80cb80b341fcbf3256b236497c3`
**Prepared:** 2026-07-28
**First execution plan:** [V4.3.3R_RECOVERY_FOUNDATION_PLAN.md](./V4.3.3R_RECOVERY_FOUNDATION_PLAN.md)

---

## 1. Planning rule

This document defines the intended V5 system and dependency order. It is not
permission to implement the whole system or mint its release ladder.

Before each release:

1. Re-ground in the current branch, repository state, applicable instructions,
   accepted lock documents, and current tickets.
2. Separate repository fact, accepted direction, proposal, and unresolved
   decision.
3. Select the smallest coherent vertical slice.
4. Write and approve its implementation plan.
5. Mint tickets only from the approved plan.
6. Preserve behavior unless the plan explicitly changes it.
7. Include schema migration, observability, recovery, security, tests, and
   documentation in the slice definition of done.
8. Distinguish implemented, verified, and accepted.

Every implementation handoff must state:

- goal and selected slice;
- repository context and base revision;
- constraints and invariants;
- files and durable state changed;
- verification actually run;
- migration, rollback, and recovery implications;
- remaining work and failures;
- exact commits, tickets, and artifacts.

---

## 2. Product mission

Crowley V5 is a personal cognitive operating system with a project-execution
forge.

It should provide one coherent Crowley experience that can:

- converse naturally and resume prior context;
- remember useful information without treating every transcript fragment as
  durable truth;
- locate likely attention while keeping inferred attention separate from write
  authority;
- distinguish evidence, interpretations, proposals, commitments, plans,
  tickets, executions, and verified results;
- organize life and projects through flexible Spaces;
- operate school and real-world commitments;
- plan and supervise approved agent work;
- explain what it knows, its sources, and what influenced an answer;
- survive database or machine failure through verified recovery;
- act through bounded, auditable tools without inventing authority.

> Crowley V5 is one fluent personal operating experience backed by bounded
> cognition, Spaces, personal operations, Forge execution, a control plane, and
> a recoverable data kernel.

> Rigid evidence and recovery; flexible meaning and association; explicit scope
> and transactional execution.

Automation, MCP transport, and voice remain useful reach multipliers. They do
not substitute for recovery, scope, conversation identity, operational truth,
or verified execution. Voice and hardware remain V5.x surfaces after the
operating core is trusted.

---

## 3. Grounded baseline

### 3.1 Existing strengths

The repository already provides:

- deterministic cognitive-intent classification, chunking, Spark extraction,
  promotion, lineage, and reviewed migration tooling;
- query modes, lane inference, scoring profiles, bounded Spark retrieval,
  graph reinforcement, explanations, and traces;
- tickets, ticket events, relationships, agent sync, handoffs, workflow gates,
  permission metadata, audit/rollback, and QA conventions;
- a transport-neutral tool contract prepared for MCP;
- substantial unit, acceptance, fixture, and inspection coverage;
- an import-compatible `crowley.py` facade over increasingly focused modules.

These foundations must be adapted rather than replaced.

### 3.2 Confirmed gaps

At the baseline:

- `setup_db()` is ad hoc and has no ordered migration ledger;
- required subsystem initialization can fail under broad exception suppression;
- normal SQLite connections do not enable foreign-key enforcement;
- most legacy tables do not declare foreign keys;
- chat messages have no session, thread, turn, Space, model, prompt-policy, or
  persistent trace identity;
- live prompt assembly uses global recent chat and legacy `memory_items`;
- the first active project row is the implicit global project;
- there is no complete project/Space CRUD and switch lifecycle;
- personal commitments, goals, routines, school records, and proposal review do
  not exist as first-class domains;
- Forge coordinates tickets and handoffs but does not persist or supervise
  agent executions;
- durable jobs, transactional outbox, connector reconciliation, and external
  object identities do not exist;
- the browser is a global conversation and intelligence dashboard, not yet a
  Space/session/review/run operating shell.

### 3.3 Database and artifact truth

A `crowley.db` file exists in the current workspace, but historical lock-document
counts are not automatically facts about that file. Its provenance, integrity,
schema, and continuity must be established before any corpus drain, reset, or
authoritative-state reconstruction.

Git proves source history and preserves plans, packets, tests, reports, and
historical artifacts. It does not prove that historical live rows exist in the
current database. Historical artifacts must never be replayed as fabricated
events.

The approved V4.3.3 Legacy Memory Final Drain packet is therefore supersession
candidate material, not executable truth. No cancellation, replacement, or
new ticket mint occurs until the recovery plan is approved.

---

## 4. System layers

Crowley remains one repository, initially one process, and initially one SQLite
database plus a managed artifact directory.

```text
Experience shell
    ↓
Attention and orchestration
    ↓
Cognition · Spaces · Operations · Forge
    ↓
Control plane
    ↓
Data kernel
```

### Experience shell

Conversation, Space and session navigation, Today, seven-day view, capture,
review inbox, corrections, history, run monitoring, diagnostics, and source
inspection.

### Attention and orchestration

Conversation mode, response depth, attention hypotheses, retrieval planning,
context packing, clarification, proposal creation, approval policy, and
response composition.

### Bounded domains

- **Cognition:** evidence receipts, Sparks, patterns, retrieval, correction.
- **Spaces:** purpose, outcomes, lifecycle, capabilities, bindings, and scoped
  threads.
- **Operations:** proposals, commitments, goals, routines, resources, and
  school/life planning.
- **Forge:** specifications, decisions, tickets, agent runs, artifacts, and QA.

### Control plane

Approvals, permissions, action scope, jobs, idempotency, leases, retries,
budgets, cancellation, verification, reconciliation, audit, and compensation.

### Data kernel

Ordered migrations, SQLite constraints, sources and revisions, evidence,
events, artifacts, audit, encryption, backup, restore, and integrity checks.

Domains may share typed kernel contracts and events. They must not reach
through the UI, HTTP layer, or compatibility facade to control one another.

---

## 5. Durable concepts

### Evidence receipts

Immutable or append-only source evidence:

- user and assistant messages;
- documents and source revisions;
- external snapshots and tool results;
- agent inputs and outputs;
- repository and validation state.

The existing `memory_items` table is not yet this clean abstraction. It is a
mixed legacy compatibility store. Its transition must be explicit and cannot
be declared complete merely by changing documentation.

### Sparks

Revisable cognitive interpretations:

- facts, observations, preferences, constraints, decisions, hypotheses,
  identity-relevant statements, and useful associations.

Active Sparks require source lineage. Corrections supersede or invalidate prior
interpretation without destroying evidence.

### Operational records

Domain state with explicit lifecycle:

- proposals, commitments, assignments, exams, goals, routines, tickets,
  agent runs, schedules, and approvals.

A Spark does not automatically become an operational record.

### Events

Append-only state-transition receipts such as proposal approval, deadline
correction, run launch, run failure, artifact verification, or external
reconciliation.

V5 does not require pure event sourcing. Materialized domain tables may remain
authoritative while events provide durable transition history. This hybrid is
the default planning assumption until explicitly amended.

### Materialized state

Current dashboards, briefings, status views, and summaries derived from domain
records and events.

---

## 6. System invariants

### Recovery

1. Required migration or initialization failure prevents healthy startup.
2. Migrations are ordered, transactional, repeat-safe, and recorded.
3. A backup is valid only after isolated restore and integrity verification.
4. Historical artifacts never become fabricated live events.
5. Reconstituted seed state records its authoritative source and method.
6. Derived caches, embeddings, and indexes are rebuildable.

### Evidence

1. Raw evidence is preserved.
2. Every active Spark has source lineage.
3. Every operational commitment has source lineage.
4. Corrections preserve superseded history.
5. External snapshots record source and revision/as-of identity.
6. Model output is interpretation, not independent evidence.

### Scope

Crowley maintains three separate scopes:

| Scope | Meaning | Rule |
|---|---|---|
| Attention | What D may be thinking about | May be inferred and weighted |
| Retrieval | Where Crowley should search | May be inferred with confidence |
| Action | Which records may change | Must be explicit or policy-approved |

Inferred attention never authorizes a write. Every mutation records target
scope, actor, source, and event/audit receipt.

### Operations

1. A Spark is not automatically a commitment.
2. A source mention is not automatically a deadline.
3. A plan is not a ticket; a ticket is not a run; a run is not verified
   completion.
4. Ambiguous time remains ambiguous until reviewed.
5. External effects are idempotent and reconciled.
6. Consequential actions define and execute verification behavior.

### Architecture

1. `crowley.py` remains a compatibility facade, not a new-logic home.
2. Domain modules do not import the facade or HTTP transport.
3. `app.py` contains transport assembly, not business logic.
4. Runtime dependencies become explicit; global runtime injection is
   transitional.
5. Schemas, events, and tool contracts are typed and versioned.
6. One process is acceptable; invisible global ownership is not.

---

## 7. Canonical V5 turn algorithm

This is the complete target algorithm for a meaningful interaction. A turn may
short-circuit only where later phases are unnecessary. Evidence, scope,
authorization, and audit requirements may not be silently skipped.

### Phase A — Preserve and locate

1. Accept input and assign a turn identity.
2. Preserve the raw user message as evidence.
3. Resolve or create the conversation session.
4. Resolve the thread and any explicitly named Space.
5. Estimate weighted attention candidates across Spaces, threads, entities,
   goals, time, and semantic neighborhoods.
6. Detect topic shifts, ambiguity, and cross-Space discussion.
7. Keep attention, retrieval, and action scopes separate.

### Phase B — Build grounded context

8. Interpret query mode and conversation mode.
9. Retrieve authoritative operational state first when required.
10. Retrieve relevant source receipts and revisions.
11. Retrieve precise core Sparks within retrieval scope.
12. Activate useful neighboring Sparks and patterns through bounded expansion.
13. Apply trust, sensitivity, Space, recency, contradiction, and token policies.
14. Pack structured context without duplicating full legacy memory.
15. Record the retrieval profile, candidates, selected Spark IDs, dropped
    context, and scope confidence.

### Phase C — Respond

16. Compose with stable personality and current interaction policy.
17. Distinguish stored fact, sourced operational state, inference, proposal, and
    uncertainty.
18. Stream or return the response.
19. Preserve the assistant response as evidence linked to the turn.
20. Record model/provider/version, prompt-policy version, context-packer
    version, retrieval trace, influencing Spark IDs, tool calls, errors,
    latency, and bounded usage/cost metadata.

### Phase D — Learn

21. Extract zero or more candidate Sparks from eligible turn evidence.
22. Give candidates soft cognitive coordinates.
23. Score durability using consequence, recurrence, commitment, identity
    relevance, novelty, explicit signals, source quality, and confidence.
24. Detect reinforcement, duplication, contradiction, and correction.
25. Keep uncertain material in candidate state.
26. Promote, reject, merge, supersede, or queue review through explicit policy.
27. Preserve source and transformation lineage.

### Phase E — Propose operations

28. Independently extract zero or more possible operational changes.
29. Classify each as suggestion, decision, proposal, commitment, ticket,
    schedule, or execution request.
30. Resolve exact target Space and target records.
31. Preserve ambiguous dates, entities, and consequences as ambiguity.
32. Present reviewable proposals where required.
33. Never use inferred attention alone to choose mutation scope.

### Phase F — Authorize and act

34. Evaluate approval policy using consequence, reversibility, external
    visibility, credential use, ambiguity, and Space impact.
35. Obtain explicit approval when required.
36. Commit approved local transition plus durable job/outbox state
    transactionally when external execution is involved.
37. Execute the bounded action.
38. Apply idempotency, leases, retries, timeouts, cancellation, and budgets.
39. Verify the result against explicit done conditions.
40. Reconcile local state, external identities, and artifacts.
41. Mark complete only after required verification.
42. On failure, preserve evidence, expose recovery options, and compensate or
    queue review where possible.

### Phase G — Close

43. Update persistent session attention without making it permanent action
    authority.
44. Update materialized dashboards and briefings.
45. Append final audit/event trace.
46. Surface unresolved proposals, ambiguity, failures, and follow-ups requiring
    review.

### Permitted short circuits

- Casual conversation may stop after learning.
- A factual question may stop after response when no durable update is useful.
- A capture request may learn while explicitly skipping operational proposals.
- Planning may produce proposals and stop before authorization.
- Only an approved action proceeds through execution and reconciliation.

---

## 8. End-to-end loops

### Cognitive

```text
Evidence → Locate attention → Retrieve → Answer → Extract → Promote/correct → Trace
```

### Life

```text
Capture → Proposal → Review → Commitment → Prioritize → Execute → Review/correct
```

### Forge

```text
Idea → Space → Spec → Decisions → Tickets → Runs → QA → Handoff → Lessons
```

### Recovery

```text
Migrate → Back up → Verify backup → Restore → Validate → Resume
```

V5 is earned by integrating these loops, not by accumulating disconnected
tables or endpoints.

---

## 9. Release ladder

Release numbers below express dependency order. Each release requires its own
approved plan before tickets are minted.

### V4.3.3R — Recovery Foundation and Database Adoption

- classify and preserve the current database;
- ordered migrations and audited legacy adoption;
- strict required initialization;
- foreign-key and integrity policy;
- backup manifests, encrypted off-device history, isolated restore, and clean
  bootstrap;
- incident and authoritative seed-state documentation;
- compatibility policy for mixed legacy memory;
- supersede the historical database-drain packet only after approval.

### V4.4 — Persistent Conversation and Cognitive Chat

- sessions, threads, turns, and message linkage;
- model, prompt, retrieval, response-failure, and influence traces;
- cognitive context as primary chat memory;
- token-bounded structured context;
- explicit cold-start fallback without duplicate legacy blocks;
- minimal session resume surface.

### V4.5 — Evidence, Truth, Review, and Security

- source and source-revision contracts;
- correction, invalidation, contradiction, and supersession;
- Spark and proposal review foundation;
- sensitive-field encryption, key recovery, and encrypted restore verification;
- replay corpus and measurable quality definitions.

### V4.6 — Spaces and Scoped Attention

- project/Space compatibility decision and migration;
- Space lifecycle, relationships, capabilities, bindings, and session scope;
- explicit action scope;
- weighted Space/thread/entity/goal retrieval scope;
- topic shifts, precise/exploratory retrieval, and bounded activation;
- zero cross-Space mutation through inference.

The existing Explore Activation RFC becomes adaptation input for this release
or a later attention sub-release. It is not executed unchanged.

### V4.7 — Personal Operations and Operating Shell

- proposals, commitments, goals, routines, resources, dependencies, and
  temporal precision;
- one complete capture-to-correction life loop;
- school terms, courses, assignments, exams, syllabus revisions, and review;
- Today, seven-day planning, weekly review, Space/session/review/history UI,
  correction, and bounded undo.

### V4.8 — Forge Supervisor

- repository bindings, specifications, decisions, and reviewed ticket ladders;
- persistent runs, attempts, events, artifacts, validations, and leases;
- worktree/branch isolation, heartbeat, budgets, cancellation, retry, and orphan
  recovery;
- QA and artifact reconciliation before completion;
- reviewed reusable lessons.

### V4.9 — Durable Actions and Controlled Connectors

- jobs, attempts, outbox, idempotency, retries, dead-letter review, and
  reconciliation;
- external identities, cursors, and connector health;
- MCP transport over the existing shared contract;
- GitHub, filesystem, and calendar as initial bounded connectors;
- prompt-injection defenses and crash-after-external-success tests;
- no unrestricted shell autonomy.

### V5.0 — Life-Ready Dogfood Lock

No major missing system first appears here. The lock demonstrates:

- the four end-to-end loops;
- clean bootstrap and verified restore;
- fluent-use scenarios without database access or memorized commands;
- zero reviewed cross-Space mutations caused by inference;
- agent interruption, cancellation, restart, timeout, and orphan recovery;
- reconciled external actions under retries and crashes;
- explainability, correction, history, and recovery in sustained dogfood.

Voice, custom hardware, health integrations, and financial automation remain
post-lock V5.x work.

---

## 10. Planning and evaluation gates

Metrics are not accepted merely because a number appears in a planning
document. Before a quantitative gate is binding, its corpus, sampling method,
review rubric, denominator, and minimum sample size must be defined.

Required evaluation families:

- Spark admission, correction, reinforcement, and promotion;
- session continuation and vague follow-ups;
- topic shifts and cross-Space retrieval/mutation;
- precise and exploratory recall;
- ambiguous time and syllabus revisions;
- proposal classification and approval;
- agent-run supervision and verification;
- malicious source/tool instructions;
- migration interruption, backup corruption, missing keys, duplicate delivery,
  stale leases, connector timeout, and concurrent writes.

Dogfood must track wrong-scope recall, wrong-scope mutation, rejected
promotions, commitment corrections, unresolved ambiguity, job retries, run
failures, restore drills, latency, model usage/cost, and manual bypasses.

---

## 11. Open architectural decisions

These remain explicit and block only the slices that depend on them:

1. Extend `projects` into Spaces or add `spaces` with a compatibility layer?
2. Hybrid domain state plus events, or a stronger event-authoritative model?
3. Field-level encryption, database encryption, or a layered approach?
4. How are key recovery and portable restore separated from ciphertext?
5. May a thread be natively cross-Space?
6. Can any action Space be policy-defaulted without inline confirmation?
7. Which proposals, if any, may be automatically approved?
8. Which lifecycle interfaces are shared between commitments and tickets?
9. Which artifacts live in SQLite versus the managed artifact directory?
10. How are embedding model/version and rebuild state represented?
11. Is browser-only sufficient for the V5 lock, or is CLI parity required?
12. What dogfood duration and evidence threshold earn V5.0?

---

## 12. Mint gate

No V5 ticket packet is minted from this document directly.

The immediate plan is
[V4.3.3R_RECOVERY_FOUNDATION_PLAN.md](./V4.3.3R_RECOVERY_FOUNDATION_PLAN.md).
After Mr. Go approves or amends that plan:

1. create a new planning packet;
2. define how historical V4.3.3 tickets #491–#495 are superseded;
3. validate the packet;
4. mint only the recovery ladder;
5. require its lock before V4.4 implementation begins.
