const chatEl = document.getElementById("chat");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send");
const thinkingEl = document.getElementById("thinking");
const healthDot = document.getElementById("health-dot");
const versionLabel = document.getElementById("version-label");
const brainLabel = document.getElementById("brain-label");
const refreshBtn = document.getElementById("refresh-panels");
const worldProjectEl = document.getElementById("world-project");
const worldStateEl = document.getElementById("world-state");
const phaseProgressEl = document.getElementById("phase-progress");
const phaseProgressLabelEl = document.getElementById("phase-progress-label");
const phaseProgressCountEl = document.getElementById("phase-progress-count");
const phaseProgressFillEl = document.getElementById("phase-progress-fill");
const stateSyncEl = document.getElementById("state-sync");
const panelTicketsEl = document.getElementById("panel-tickets");
const ticketDetailEl = document.getElementById("ticket-detail");
const panelTasksEl = document.getElementById("panel-tasks");
const panelLoopsEl = document.getElementById("panel-loops");
const panelDecisionsEl = document.getElementById("panel-decisions");
const panelAgentFeedEl = document.getElementById("panel-agent-feed");
const panelMemoryEl = document.getElementById("panel-memory");
const memorySearchEl = document.getElementById("memory-search");
const memorySourceEl = document.getElementById("memory-source");
const memoryTypeEl = document.getElementById("memory-type");
const memoryStatusEl = document.getElementById("memory-status");
const memoryLayerEl = document.getElementById("memory-layer");
const memoryCountSummaryEl = document.getElementById("memory-count-summary");
const diagnosticsBtn = document.getElementById("run-diagnostics");
const contextToggle = document.getElementById("context-toggle");
const contextDrawer = document.getElementById("context-drawer");
const contextBody = document.getElementById("context-body");
const contextSummary = document.getElementById("context-summary");
const contextPanelMeta = document.getElementById("context-panel-meta");
const liveSyncPill = document.getElementById("live-sync-pill");
const liveSyncLabel = document.getElementById("live-sync-label");
const composePhaseEl = document.getElementById("compose-phase");
const contextTabs = document.querySelectorAll(".context-tab");
const objectiveEl = document.getElementById("current-objective");

let streaming = false;
let pollTimer = null;
let activeContextTab = "tickets";
let selectedTicketId = null;
let lastDashboardFingerprint = "";
let lastDashboardData = null;
let memorySearchTimer = null;
const EXTRACTION_REFRESH_MS = 2000;
const LIVE_POLL_MS = 5000;
const OBJECTIVE_FALLBACK = "Nothing pinned — just talk.";
const INPUT_MAX_HEIGHT = 192;

function setBusy(busy) {
  streaming = busy;
  inputEl.disabled = busy;
  sendBtn.disabled = busy;
  if (diagnosticsBtn) diagnosticsBtn.disabled = busy;
  if (!busy) hideThinking();
}

function setThinking(active, label = "Thinking") {
  if (!thinkingEl) return;
  const labelEl = thinkingEl.querySelector(".thinking-label");
  if (labelEl) labelEl.textContent = label;
  thinkingEl.classList.toggle("hidden", !active);
}

function hideThinking() {
  thinkingEl?.classList.add("hidden");
}

function autoGrowInput() {
  if (!inputEl) return;
  inputEl.style.height = "auto";
  const next = Math.min(inputEl.scrollHeight, INPUT_MAX_HEIGHT);
  inputEl.style.height = `${next}px`;
}

function resetInput() {
  if (!inputEl) return;
  inputEl.value = "";
  autoGrowInput();
}

function formatRelativeTime(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const sec = Math.floor((Date.now() - then.getTime()) / 1000);
  if (sec < 10) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return then.toLocaleString();
}

function updateComposePhase(progress) {
  if (!composePhaseEl) return;
  if (!progress?.current || !progress?.total) {
    composePhaseEl.textContent = "";
    composePhaseEl.classList.add("hidden");
    return;
  }
  composePhaseEl.textContent = `Phase ${progress.current}/${progress.total}`;
  composePhaseEl.classList.remove("hidden");
}

function dashboardFingerprint(data) {
  const state = data.state || {};
  const counts = data.counts || {};
  return JSON.stringify({
    phase: state.phase,
    focus: state.focus,
    next: state.next_action,
    updated: state.updated_at,
    counts,
    synced: data.synced_at,
  });
}

function flashLiveUpdate() {
  contextDrawer?.classList.add("is-updated");
  liveSyncPill?.classList.add("is-pulse");
  window.setTimeout(() => {
    contextDrawer?.classList.remove("is-updated");
    liveSyncPill?.classList.remove("is-pulse");
  }, 700);
}

function updateLiveSyncLabel(syncedAt) {
  if (!liveSyncLabel) return;
  const rel = formatRelativeTime(syncedAt);
  liveSyncLabel.textContent = rel ? `Live · ${rel}` : "Live";
  if (liveSyncPill && syncedAt) {
    liveSyncPill.title = `Dashboard synced ${rel || syncedAt}`;
  }
}

function updateTabBadges(counts = {}) {
  const map = {
    tickets: counts.tickets_open_total || counts.tickets_open || 0,
    tasks: counts.tasks_open || 0,
    loops: counts.loops_open || 0,
    decisions: counts.decisions || 0,
    agent_feed: counts.agent_feed || 0,
    memory: counts.memory || 0,
  };
  contextTabs.forEach((tab) => {
    const key = tab.dataset.tab;
    const label = tab.dataset.label || key;
    const count = map[key] || 0;
    tab.textContent = count > 0 ? `${label} (${count})` : label;
    tab.classList.toggle("has-items", count > 0);
  });
}

const PANEL_META = {
  tickets: {
    title: "Open tickets",
    empty: "No open tickets.",
    describe: (items) => `${items.length} ticket${items.length === 1 ? "" : "s"} on the board`,
  },
  tasks: {
    title: "Open tasks",
    empty: "No open tasks.",
    describe: (items) => `${items.length} actionable item${items.length === 1 ? "" : "s"}`,
  },
  loops: {
    title: "Open loops",
    empty: "No open loops.",
    describe: (items) => {
      const p1 = items.filter((l) => Number(l.priority) === 1).length;
      return p1
        ? `${items.length} open · ${p1} high priority`
        : `${items.length} unresolved item${items.length === 1 ? "" : "s"}`;
    },
  },
  decisions: {
    title: "Recent decisions",
    empty: "No recent decisions.",
    describe: (items) => `${items.length} logged decision${items.length === 1 ? "" : "s"}`,
  },
  agent_feed: {
    title: "Agent feed",
    empty: "No agent handoffs yet.",
    describe: (items) => `${items.length} recent event${items.length === 1 ? "" : "s"}`,
  },
  memory: {
    title: "Stored memory",
    empty: "No memory items yet.",
    describe: (items, data = {}) => formatMemoryCounts(data.counts || {}, items.length),
  },
};

function memoryLayerLabel(layer) {
  switch (layer) {
    case "canon":
      return "Canon";
    case "pinned":
      return "Pinned";
    default:
      return "Memory";
  }
}

function memoryLayerBadge(m) {
  const layer = m.memory_layer || (m.is_canon ? "canon" : m.is_pinned ? "pinned" : "memory");
  const label = memoryLayerLabel(layer);
  return `<span class="memory-badge memory-badge-${escapeHtml(layer)}">${escapeHtml(label)}</span>`;
}

function itemsForTab(data, tab) {
  switch (tab) {
    case "tickets":
      return data.tickets || [];
    case "tasks":
      return data.tasks || [];
    case "loops":
      return data.loops || [];
    case "decisions":
      return data.decisions || [];
    case "agent_feed":
      return (data.agent_activity && data.agent_activity.recent) || [];
    case "memory":
      return data.memory_items || [];
    default:
      return [];
  }
}

function updatePanelMeta(data, tab = activeContextTab) {
  if (!contextPanelMeta) return;
  const meta = PANEL_META[tab];
  if (!meta) {
    contextPanelMeta.textContent = "";
    return;
  }
  const items = itemsForTab(data, tab);
  if (!items.length) {
    contextPanelMeta.textContent = meta.empty;
    return;
  }
  contextPanelMeta.textContent = `${meta.title} — ${meta.describe(items, data)}`;
}

function formatMemoryCounts(counts = {}, displayed = 0, totalOverride = null) {
  const active = counts.memory_active ?? counts.memory ?? 0;
  const total = totalOverride ?? counts.memory_total ?? active;
  const shown = counts.memory_displayed ?? displayed;
  return `${active} active / ${total} total · showing ${shown}`;
}

function setMemoryCountSummary(text) {
  if (memoryCountSummaryEl) memoryCountSummaryEl.textContent = text || "—";
}

function renderMemoryItems(items = []) {
  renderPanelList(panelMemoryEl, items, (m) => {
    const meta = [m.memory_type, m.source].filter(Boolean).join(" · ");
    const when = m.created_at ? formatRelativeTime(m.created_at) : "";
    const timeMeta = when ? ` · ${when}` : "";
    return (
      `${memoryLayerBadge(m)}` +
      `<span class="meta">${escapeHtml(meta)}${escapeHtml(timeMeta)}</span> ` +
      `${escapeHtml(m.display || m.content || "")}`
    );
  });
}

function memoryFilterParams() {
  return {
    q: (memorySearchEl?.value || "").trim(),
    layer: memoryLayerEl?.value || "",
    source: memorySourceEl?.value || "",
    memory_type: memoryTypeEl?.value || "",
    status: memoryStatusEl?.value || "active",
  };
}

function applyMemoryLayerFilter(items, layer) {
  if (!layer) return items;
  return items.filter((item) => {
    const itemLayer =
      item.memory_layer || (item.is_canon ? "canon" : item.is_pinned ? "pinned" : "memory");
    return itemLayer === layer;
  });
}

function hasMemoryFilters() {
  const params = memoryFilterParams();
  return Boolean(
    params.q ||
      params.layer ||
      params.source ||
      params.memory_type ||
      (params.status && params.status !== "active")
  );
}

function ticketStatusClass(status) {
  const normalized = String(status || "open").toLowerCase().replace(/\s+/g, "_");
  if (normalized === "in_progress") return "ticket-status-in_progress";
  if (
    normalized === "open" ||
    normalized === "claimed" ||
    normalized === "blocked" ||
    normalized === "done" ||
    normalized === "cancelled"
  ) {
    return `ticket-status-${normalized}`;
  }
  return "ticket-status-open";
}

function parseTicketDescription(description) {
  const text = String(description || "").trim();
  if (!text) return { body: "", acceptance: [] };
  const marker = /\n\s*Acceptance:\s*\n/i;
  const match = text.match(marker);
  if (!match || match.index === undefined) return { body: text, acceptance: [] };
  const body = text.slice(0, match.index).trim();
  const rest = text.slice(match.index + match[0].length);
  const acceptance = rest
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("- "))
    .map((line) => line.slice(2).trim())
    .filter(Boolean);
  return { body, acceptance };
}

function formatTicketTimestamp(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  const relative = formatRelativeTime(iso);
  return `<time datetime="${escapeHtml(iso)}" title="${escapeHtml(date.toLocaleString())}">${escapeHtml(relative || date.toLocaleString())}</time>`;
}

function formatTicketEventDetail(event) {
  const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
  switch (event.event_type) {
    case "status_change":
      return `${payload.from || "?"} → ${payload.to || "?"}`;
    case "comment":
      return String(payload.text || "");
    case "cancelled":
      return String(payload.reason || "");
    case "assignee_change":
      return `${payload.from || "?"} → ${payload.to || "?"}`;
    case "priority_change":
      return `P${payload.from ?? "?"} → P${payload.to ?? "?"}`;
    case "created":
      return String(payload.title || "Ticket created");
    case "claimed":
      return String(payload.status || "claimed");
    case "handoff_linked":
      return payload.memory_id
        ? `handoff memory #${payload.memory_id}`
        : "handoff linked";
    default:
      return Object.keys(payload).length ? JSON.stringify(payload) : String(event.event_type || "");
  }
}

function renderTicketDetail(detail) {
  if (!ticketDetailEl) return;
  const ticket = detail.ticket || {};
  const events = Array.isArray(detail.events) ? detail.events : [];
  const parsed = parseTicketDescription(ticket.description);
  const status = String(ticket.status || "open");
  const statusClass = ticketStatusClass(status);
  const acceptanceHtml = parsed.acceptance.length
    ? `<section class="ticket-detail-section"><h5>Acceptance</h5><ul class="ticket-detail-list">${parsed.acceptance
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("")}</ul></section>`
    : "";
  const descriptionHtml = parsed.body
    ? `<section class="ticket-detail-section"><h5>Description</h5><p class="ticket-detail-text">${escapeHtml(parsed.body)}</p></section>`
    : "";
  const linked = detail.linked_handoff;
  const linkedHtml =
    linked && linked.memory_id
      ? `<section class="ticket-detail-section"><h5>Linked handoff</h5><p class="ticket-detail-text">` +
        `memory #${escapeHtml(String(linked.memory_id))}` +
        (linked.source ? ` · ${escapeHtml(String(linked.source))}` : "") +
        (linked.memory_type ? ` · ${escapeHtml(String(linked.memory_type))}` : "") +
        (linked.summary ? ` — ${escapeHtml(String(linked.summary))}` : "") +
        `</p></section>`
      : ticket.linked_memory_id
        ? `<section class="ticket-detail-section"><h5>Linked handoff</h5><p class="ticket-detail-text">memory #${escapeHtml(String(ticket.linked_memory_id))}</p></section>`
        : "";
  const eventsHtml = events.length
    ? `<section class="ticket-detail-section"><h5>History</h5><ul class="ticket-detail-events">${events
        .map((event) => {
          const when = event.created_at ? formatRelativeTime(event.created_at) : "";
          const detailText = formatTicketEventDetail(event);
          return (
            `<li>` +
            `<span class="ticket-event-head">` +
            `<span class="meta">${escapeHtml(String(event.event_type || "event"))}</span> ` +
            `<span class="meta">${escapeHtml(String(event.actor || "system"))}</span>` +
            (when ? ` <span class="meta">· ${escapeHtml(when)}</span>` : "") +
            `</span>` +
            (detailText ? `<span class="ticket-event-detail">${escapeHtml(detailText)}</span>` : "") +
            `</li>`
          );
        })
        .join("")}</ul></section>`
    : `<section class="ticket-detail-section"><p class="ticket-detail-empty">No ticket events yet.</p></section>`;

  ticketDetailEl.innerHTML =
    `<header class="ticket-detail-header">` +
    `<span class="ticket-status-badge ${statusClass}">${escapeHtml(status)}</span>` +
    `<h4 class="ticket-detail-title">#${escapeHtml(String(ticket.id))} ${escapeHtml(String(ticket.title || ""))}</h4>` +
    `</header>` +
    `<dl class="ticket-detail-meta">` +
    `<div><dt>Assignee</dt><dd>${escapeHtml(String(ticket.assignee || "unassigned"))}</dd></div>` +
    `<div><dt>Priority</dt><dd>P${escapeHtml(String(ticket.priority ?? "?"))}</dd></div>` +
    `<div><dt>Created</dt><dd>${formatTicketTimestamp(ticket.created_at)}</dd></div>` +
    `<div><dt>Updated</dt><dd>${formatTicketTimestamp(ticket.updated_at)}</dd></div>` +
    `</dl>` +
    linkedHtml +
    descriptionHtml +
    acceptanceHtml +
    eventsHtml;
  ticketDetailEl.classList.remove("hidden");
  document
    .querySelector('.context-panel[data-panel="tickets"]')
    ?.classList.add("has-detail");
}

function clearTicketDetail(message = "") {
  if (!ticketDetailEl) return;
  ticketDetailEl.innerHTML = message
    ? `<p class="ticket-detail-empty">${escapeHtml(message)}</p>`
    : "";
  ticketDetailEl.classList.toggle("hidden", !message);
  document
    .querySelector('.context-panel[data-panel="tickets"]')
    ?.classList.toggle("has-detail", Boolean(message));
}

function highlightSelectedTicket() {
  if (!panelTicketsEl) return;
  panelTicketsEl.querySelectorAll(".ticket-item").forEach((item) => {
    const ticketId = Number(item.dataset.ticketId);
    item.classList.toggle("is-selected", selectedTicketId === ticketId);
  });
}

async function loadTicketDetail(ticketId) {
  if (!ticketDetailEl || !ticketId) return;
  ticketDetailEl.classList.remove("hidden");
  ticketDetailEl.innerHTML = `<p class="ticket-detail-loading">Loading ticket #${escapeHtml(String(ticketId))}…</p>`;
  document
    .querySelector('.context-panel[data-panel="tickets"]')
    ?.classList.add("has-detail");
  try {
    const res = await fetch(`/api/tickets/${ticketId}`);
    if (!res.ok) {
      clearTicketDetail("Ticket detail unavailable.");
      return;
    }
    const detail = await res.json();
    renderTicketDetail(detail);
    highlightSelectedTicket();
  } catch {
    clearTicketDetail("Ticket detail unavailable.");
  }
}

function selectTicket(ticketId) {
  if (!ticketId) return;
  if (selectedTicketId === ticketId) {
    selectedTicketId = null;
    clearTicketDetail();
    highlightSelectedTicket();
    return;
  }
  selectedTicketId = ticketId;
  highlightSelectedTicket();
  loadTicketDetail(ticketId);
}

function ticketRowHtml(t, { child = false, initiative = false, selected = false } = {}) {
  const initiativeMeta = initiative
    ? `<span class="meta ticket-initiative">initiative</span> `
    : "";
  const parentMeta =
    t.parent_id && !child
      ? `<span class="meta">parent #${escapeHtml(String(t.parent_id))}</span> `
      : "";
  const statusClass = ticketStatusClass(t.status);
  return (
    `<li class="ticket-item${child ? " ticket-child" : ""}${selected ? " is-selected" : ""}" data-ticket-id="${t.id}">` +
    `<span class="task-row">` +
    `<span class="task-text">` +
    initiativeMeta +
    `<span class="meta">#${t.id}</span> ` +
    parentMeta +
    `<span class="meta ticket-status ${statusClass}">${escapeHtml(String(t.status))}</span> ` +
    `<span class="meta">${escapeHtml(String(t.assignee))}</span> ` +
    `${escapeHtml(t.title)}</span>` +
    `<button type="button" class="ticket-done-btn" data-ticket-id="${t.id}" title="Mark done" aria-label="Mark ticket ${t.id} done">✓</button>` +
    `</span>` +
    `</li>`
  );
}

function renderTicketsPanel(groups = [], flat = []) {
  if (!panelTicketsEl) return;
  const blocks = [];
  if (groups.length) {
    for (const group of groups) {
      const ticket = group.ticket || {};
      blocks.push(
        ticketRowHtml(ticket, {
          initiative: Boolean(group.is_initiative),
          selected: selectedTicketId === Number(ticket.id),
        })
      );
      for (const child of group.children || []) {
        blocks.push(
          ticketRowHtml(child, {
            child: true,
            selected: selectedTicketId === Number(child.id),
          })
        );
      }
    }
  } else {
    for (const ticket of flat) {
      blocks.push(
        ticketRowHtml(ticket, { selected: selectedTicketId === Number(ticket.id) })
      );
    }
  }
  panelTicketsEl.innerHTML = blocks.join("");
}

function agentSourceClass(source) {
  const normalized = String(source || "").toLowerCase();
  if (normalized === "cursor") return "agent-source-cursor";
  if (normalized === "codex") return "agent-source-codex";
  if (normalized === "crowley") return "agent-source-crowley";
  return "agent-source-other";
}

function renderAgentFeedPanel(events = []) {
  if (!panelAgentFeedEl) return;
  renderPanelList(panelAgentFeedEl, events, (event) => {
    const source = String(event.source || "unknown");
    const when = event.created_at ? formatRelativeTime(event.created_at) : "";
    const typeMeta = event.memory_type ? escapeHtml(String(event.memory_type)) : "";
    const summary = escapeHtml(String(event.summary || "(no summary)"));
    const ticketLinks = Array.isArray(event.linked_ticket_ids) ? event.linked_ticket_ids : [];
    const ticketMeta = ticketLinks.length
      ? `<span class="meta">· ticket #${escapeHtml(String(ticketLinks[0]))}</span> `
      : "";
    const nextAction = event.next_action
      ? `<span class="agent-feed-next">Next: ${escapeHtml(String(event.next_action))}</span>`
      : "";
    return (
      `<span class="agent-feed-row">` +
      `<span class="agent-feed-head">` +
      `<span class="meta ${agentSourceClass(source)}">${escapeHtml(source)}</span> ` +
      (typeMeta ? `<span class="meta">${typeMeta}</span> ` : "") +
      ticketMeta +
      (when ? `<span class="meta">· ${escapeHtml(when)}</span>` : "") +
      `</span>` +
      `<span class="agent-feed-summary">${summary}</span>` +
      nextAction +
      `</span>`
    );
  });
}

function loopPriorityClass(priority) {
  const p = Number(priority);
  if (p === 1) return "priority-high";
  if (p === 2) return "priority-med";
  return "priority-low";
}

function updateCurrentObjective(state = {}, progress = null) {
  if (!objectiveEl) return;
  const focus = (state.focus || "").trim();
  const nextAction = (state.next_action || "").trim();
  const text = focus || nextAction || OBJECTIVE_FALLBACK;
  const isPlaceholder = !focus && !nextAction;
  objectiveEl.textContent = text;
  objectiveEl.classList.toggle("is-placeholder", isPlaceholder);
  updateComposePhase(progress);
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inlineMarkdown(text) {
  let s = escapeHtml(text);
  s = s.replace(/`([^`]+)`/g, "<code class=\"inline-code\">$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  s = s.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  return s;
}

function renderMarkdownBlocks(text) {
  const lines = String(text).split("\n");
  let html = "";
  let inList = null;
  let paragraph = [];

  function flushParagraph() {
    if (!paragraph.length) return;
    html += `<p>${inlineMarkdown(paragraph.join(" "))}</p>`;
    paragraph = [];
  }

  function closeList() {
    if (!inList) return;
    html += `</${inList}>`;
    inList = null;
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      closeList();
      continue;
    }

    const heading =
      trimmed.match(/^###\s+(.+)/) ||
      trimmed.match(/^##\s+(.+)/) ||
      trimmed.match(/^#\s+(.+)/);
    const bullet = trimmed.match(/^[-*]\s+(.+)/);
    const ordered = trimmed.match(/^\d+\.\s+(.+)/);
    const isRule = trimmed === "---" || trimmed === "***" || trimmed === "___";

    if (heading) {
      flushParagraph();
      closeList();
      const level = trimmed.startsWith("###") ? 3 : trimmed.startsWith("##") ? 2 : 1;
      html += `<h${level}>${inlineMarkdown(heading[1])}</h${level}>`;
      continue;
    }

    if (isRule) {
      flushParagraph();
      closeList();
      html += "<hr>";
      continue;
    }

    if (bullet) {
      flushParagraph();
      if (inList !== "ul") {
        closeList();
        html += "<ul>";
        inList = "ul";
      }
      html += `<li>${inlineMarkdown(bullet[1])}</li>`;
      continue;
    }

    if (ordered) {
      flushParagraph();
      if (inList !== "ol") {
        closeList();
        html += "<ol>";
        inList = "ol";
      }
      html += `<li>${inlineMarkdown(ordered[1])}</li>`;
      continue;
    }

    closeList();
    paragraph.push(trimmed);
  }

  flushParagraph();
  closeList();
  return html;
}

function renderMarkdown(text) {
  const input = String(text || "");
  if (!input.trim()) return "";

  const parts = [];
  const fenceRe = /```(\w*)\n?([\s\S]*?)```/g;
  let last = 0;
  let match;

  while ((match = fenceRe.exec(input)) !== null) {
    if (match.index > last) {
      parts.push({ type: "text", content: input.slice(last, match.index) });
    }
    parts.push({ type: "code", lang: match[1] || "", content: match[2] });
    last = match.index + match[0].length;
  }
  if (last < input.length) {
    parts.push({ type: "text", content: input.slice(last) });
  }
  if (!parts.length) {
    parts.push({ type: "text", content: input });
  }

  return parts
    .map((part) => {
      if (part.type === "code") {
        const lang = part.lang
          ? `<span class="code-lang">${escapeHtml(part.lang)}</span>`
          : "";
        return (
          `<pre class="code-block">${lang}` +
          `<code>${escapeHtml(part.content.replace(/\n$/, ""))}</code></pre>`
        );
      }
      return renderMarkdownBlocks(part.content);
    })
    .join("");
}

function formatUserMessage(content) {
  const text = String(content || "");
  if (!text.trim()) {
    return '<div class="message-body user-body"></div>';
  }
  const paragraphs = text.split(/\n{2,}/).map((block) => {
    const inner = escapeHtml(block).replace(/\n/g, "<br>");
    return `<p>${inner}</p>`;
  });
  return `<div class="message-body user-body">${paragraphs.join("")}</div>`;
}

function formatAssistantMessage(content, { streaming = false } = {}) {
  const text = String(content || "");
  if (streaming) {
    const inner = escapeHtml(text).replace(/\n/g, "<br>");
    return `<div class="message-body prose is-streaming">${inner || "&nbsp;"}</div>`;
  }
  if (!text.trim()) {
    return '<div class="message-body prose"></div>';
  }
  return `<div class="message-body prose">${renderMarkdown(text)}</div>`;
}

function attachMessageExpand(wrap, raw) {
  const body = wrap.querySelector(".message-body");
  if (!body || wrap.querySelector(".message-expand")) return;

  const lineCount = String(raw || "").split("\n").length;
  const long = lineCount >= 22 || String(raw || "").length >= 1600;
  if (!long) return;

  body.classList.add("is-collapsible", "is-collapsed");

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "message-expand";
  btn.textContent = "Show full response";
  btn.addEventListener("click", () => {
    body.classList.remove("is-collapsed");
    btn.remove();
  });
  wrap.appendChild(btn);
}

function setMessageContent(wrap, raw, { streaming = false } = {}) {
  const labelEl = wrap.querySelector(".message-label");
  const defaultLabel = wrap.classList.contains("user")
    ? "You"
    : wrap.classList.contains("diagnostics")
      ? "Diagnostics"
      : "Crowley";
  const labelHtml = labelEl
    ? labelEl.outerHTML
    : `<span class="message-label">${defaultLabel}</span>`;

  const isAssistant =
    wrap.classList.contains("crowley") || wrap.classList.contains("diagnostics");

  if (isAssistant) {
    wrap.innerHTML =
      labelHtml + formatAssistantMessage(raw, { streaming });
    wrap.dataset.raw = raw;
    if (!streaming) {
      attachMessageExpand(wrap, raw);
    }
    return;
  }

  wrap.innerHTML = labelHtml + formatUserMessage(raw);
  wrap.dataset.raw = raw;
}

function renderMessage(role, content, extraClass = "") {
  const wrap = document.createElement("div");
  const label = role === "user" ? "You" : "Crowley";
  const cssRole = role === "user" ? "user" : "crowley";
  wrap.className = `message ${cssRole} ${extraClass}`.trim();
  setMessageContent(wrap, content, {
    streaming: extraClass.includes("streaming"),
  });
  chatEl.appendChild(wrap);
  chatEl.scrollTop = chatEl.scrollHeight;
  return wrap;
}

function renderError(message) {
  const wrap = document.createElement("div");
  wrap.className = "message error";
  wrap.textContent = message;
  chatEl.appendChild(wrap);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function renderDiagnosticsBlock(content, extraClass = "") {
  const wrap = document.createElement("div");
  wrap.className = `message diagnostics ${extraClass}`.trim();
  wrap.dataset.ephemeral = "true";
  setMessageContent(wrap, content, {
    streaming: extraClass.includes("streaming"),
  });
  chatEl.appendChild(wrap);
  chatEl.scrollTop = chatEl.scrollHeight;
  return wrap;
}

function clearEmptyState() {
  const empty = chatEl.querySelector(".empty-state");
  if (empty) empty.remove();
}

function showEmptyState() {
  if (chatEl.children.length) return;
  const empty = document.createElement("p");
  empty.className = "empty-state";
  empty.textContent =
    "Say anything — build, plan, or think out loud.";
  chatEl.appendChild(empty);
}

function renderPanelList(el, items, renderItem) {
  el.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.textContent = "(none)";
    el.appendChild(li);
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    li.innerHTML = renderItem(item);
    el.appendChild(li);
  }
}

function renderWorldState(fields) {
  worldStateEl.innerHTML = "";
  for (const [label, value] of fields) {
    const block = document.createElement("div");
    block.innerHTML = `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`;
    worldStateEl.appendChild(block);
  }
}

function renderPhaseProgress(progress) {
  if (!phaseProgressEl) return;
  if (!progress || !progress.total) {
    phaseProgressEl.classList.add("hidden");
    return;
  }
  phaseProgressEl.classList.remove("hidden");
  const pct = Math.round((progress.current / progress.total) * 100);
  if (phaseProgressLabelEl) {
    phaseProgressLabelEl.textContent = progress.label || `Phase ${progress.current}`;
  }
  if (phaseProgressCountEl) {
    phaseProgressCountEl.textContent = `${progress.current} / ${progress.total}`;
  }
  if (phaseProgressFillEl) {
    phaseProgressFillEl.style.width = `${pct}%`;
  }
}

function renderStateSync(state, version, releaseLabel, filesystem = {}) {
  if (!stateSyncEl) return;
  const parts = [];
  const fsAsOf = filesystem?.project_state_as_of;
  if (fsAsOf) {
    parts.push(String(fsAsOf).replace(/\*\*/g, "").trim());
  } else if (version) {
    parts.push(`v${version}`);
  }
  if (state?.updated_at) {
    const rel = formatRelativeTime(state.updated_at);
    const by = state.updated_by ? ` · ${state.updated_by}` : "";
    parts.push(`DB ${rel}${by}`);
  }
  stateSyncEl.textContent = parts.join(" · ") || "—";
  const fsTitle = filesystem?.versions_current || releaseLabel || "";
  stateSyncEl.title = fsTitle || state?.updated_at || "";
}

function renderDashboard(data, { animate = false } = {}) {
  const fingerprint = dashboardFingerprint(data);
  const changed = fingerprint !== lastDashboardFingerprint;
  const shouldFlash =
    animate && changed && lastDashboardFingerprint !== "";
  lastDashboardFingerprint = fingerprint;
  if (shouldFlash) flashLiveUpdate();

  updateLiveSyncLabel(data.synced_at);
  updateTabBadges(data.counts || {});

  if (!data.project) {
    worldProjectEl.textContent = "No active project";
    updateCurrentObjective();
    renderWorldState([]);
    renderPhaseProgress(null);
    renderStateSync(null, data.version, data.release_label);
    renderPanelList(panelTasksEl, [], () => "");
    renderPanelList(panelLoopsEl, [], () => "");
    renderPanelList(panelDecisionsEl, [], () => "");
    renderPanelList(panelAgentFeedEl, [], () => "");
    renderPanelList(panelMemoryEl, [], () => "");
    clearTicketDetail();
    selectedTicketId = null;
    updateContextSummary(data, null);
    updatePanelMeta(data);
    return;
  }

  worldProjectEl.textContent = `${data.project.name} (${data.project.status})`;
  const state = data.state || {};
  updateCurrentObjective(state, data.phase_progress);
  renderPhaseProgress(data.phase_progress);
  renderStateSync(state, data.version, data.release_label, data.filesystem || {});
  renderWorldState([
    ["Phase", state.phase || "(unset)"],
    ["Focus", state.focus || "(unset)"],
    ["Risk", state.current_risk || "(unset)"],
    ["Next action", state.next_action || "(unset)"],
    ["What changed", state.what_changed || "(unset)"],
  ]);

  renderTicketsPanel(data.ticket_groups || [], data.tickets || []);
  if (selectedTicketId) {
    loadTicketDetail(selectedTicketId);
  }

  renderPanelList(panelTasksEl, data.tasks || [], (t) =>
    `<span class="task-row">` +
    `<span class="task-text"><span class="meta">#${t.id}</span> ${escapeHtml(t.title)}</span>` +
    `<button type="button" class="task-done-btn" data-task-id="${t.id}" title="Mark done" aria-label="Mark task ${t.id} done">✓</button>` +
    `</span>`
  );

  renderPanelList(panelLoopsEl, data.loops || [], (l) => {
    const pClass = loopPriorityClass(l.priority);
    return (
      `<span class="meta ${pClass}">P${l.priority}</span>` +
      `<span class="meta">#${l.id}</span> ${escapeHtml(l.description)}`
    );
  });

  const decisions = [...(data.decisions || [])].reverse();
  renderPanelList(panelDecisionsEl, decisions, (d) =>
    `<span class="meta">[${d.id}]</span> ${escapeHtml(d.summary)}`
  );

  const agentEvents = (data.agent_activity && data.agent_activity.recent) || [];
  renderAgentFeedPanel(agentEvents);

  const memoryItems = [...(data.memory_items || [])].reverse();
  renderMemoryItems(memoryItems);
  setMemoryCountSummary(formatMemoryCounts(data.counts || {}, memoryItems.length));

  updateContextSummary(data, state);
  updatePanelMeta(data);
  lastDashboardData = data;
}

async function loadHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    healthDot.classList.toggle("ok", data.status === "ok");
    healthDot.classList.toggle("error", data.status !== "ok");
    healthDot.title = data.status === "ok" ? "Online" : "Degraded";
    if (versionLabel && data.version) {
      versionLabel.textContent = `v${data.version}`;
      versionLabel.title = data.release_label || "";
    }
    if (data.brain) {
      brainLabel.textContent = data.brain;
    }
  } catch {
    healthDot.classList.add("error");
    healthDot.title = "Offline";
    if (versionLabel) versionLabel.textContent = "offline";
  }
}

async function completeTicket(ticketId) {
  if (!ticketId || streaming) return;
  try {
    const res = await fetch(`/api/tickets/${ticketId}/done?actor=mr_go`, { method: "POST" });
    if (!res.ok) return;
    await refreshPanels({ animate: true });
  } catch {
    /* ignore */
  }
}

async function completeTask(taskId) {
  if (!taskId || streaming) return;
  try {
    const res = await fetch(`/api/tasks/${taskId}/done`, { method: "POST" });
    if (!res.ok) return;
    await refreshPanels({ animate: true });
  } catch {
    /* ignore */
  }
}

async function refreshPanels({ animate = false } = {}) {
  try {
    const res = await fetch("/api/world");
    const data = await res.json();
    renderDashboard(data, { animate });
    if (hasMemoryFilters()) {
      loadMemoryItems();
    }
  } catch {
    if (liveSyncLabel) liveSyncLabel.textContent = "Offline";
    if (activeContextTab === "agent_feed" && contextPanelMeta) {
      contextPanelMeta.textContent = "Agent feed unavailable.";
    }
  }
}

async function loadMemoryItems() {
  if (!panelMemoryEl) return;
  const params = new URLSearchParams();
  const filters = memoryFilterParams();
  params.set("limit", "10");
  params.set("offset", "0");
  Object.entries(filters).forEach(([key, value]) => {
    if (key === "layer" || !value) return;
    params.set(key, value);
  });

  try {
    const res = await fetch(`/api/memory-items?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();
    const items = applyMemoryLayerFilter(data.items || [], filters.layer);
    renderMemoryItems([...items].reverse());
    if (lastDashboardData) {
      lastDashboardData.memory_items = items;
      const counts = lastDashboardData.counts || {};
      counts.memory_displayed = items.length;
      lastDashboardData.counts = counts;
    }
    const counts = lastDashboardData?.counts || {};
    setMemoryCountSummary(formatMemoryCounts(counts, items.length, data.total ?? null));
    if (activeContextTab === "memory" && lastDashboardData) {
      updatePanelMeta(lastDashboardData, "memory");
    }
  } catch {
    setMemoryCountSummary("Memory unavailable");
  }
}

function scheduleMemoryLoad() {
  if (memorySearchTimer) window.clearTimeout(memorySearchTimer);
  memorySearchTimer = window.setTimeout(() => loadMemoryItems(), 180);
}

function updateContextSummary(data = {}, state = null) {
  if (!contextSummary) return;
  const counts = data.counts || {};
  const parts = [];

  if (data.phase_progress?.current && data.phase_progress?.total) {
    parts.push(
      `Phase ${data.phase_progress.current}/${data.phase_progress.total}`
    );
  } else if (state?.phase) {
    const short = String(state.phase).slice(0, 28);
    parts.push(short.length < String(state.phase).length ? `${short}…` : short);
  }

  if (counts.tickets_open_total) {
    parts.push(`${counts.tickets_open_total} Ticket${counts.tickets_open_total !== 1 ? "s" : ""}`);
  }
  if (counts.tasks_open) parts.push(`${counts.tasks_open} Task${counts.tasks_open !== 1 ? "s" : ""}`);
  if (counts.loops_open) parts.push(`${counts.loops_open} Loop${counts.loops_open !== 1 ? "s" : ""}`);
  if (counts.decisions) parts.push(`${counts.decisions} Dec`);
  if (counts.memory) parts.push(`${counts.memory} Mem`);

  const synced = data.synced_at ? formatRelativeTime(data.synced_at) : "";
  if (synced) parts.push(`↻ ${synced}`);

  contextSummary.textContent = parts.length ? parts.join(" • ") : "No open context";
}

function setContextTab(name) {
  activeContextTab = name;
  contextTabs.forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".context-panel").forEach((panel) => {
    const active = panel.dataset.panel === name;
    panel.classList.toggle("is-active", active);
    panel.hidden = !active;
  });
  if (lastDashboardData) updatePanelMeta(lastDashboardData, name);
}

function toggleContextDrawer() {
  if (!contextDrawer || !contextBody || !contextToggle) return;
  const collapsed = contextDrawer.classList.toggle("is-collapsed");
  contextBody.classList.toggle("hidden", collapsed);
  contextToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
}

function scheduleExtractionRefresh() {
  window.setTimeout(() => refreshPanels(), EXTRACTION_REFRESH_MS);
}

function startLiveSync() {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = window.setInterval(() => {
    if (!document.hidden && !streaming) {
      refreshPanels({ animate: true });
      loadHealth();
    }
  }, LIVE_POLL_MS);
}

async function loadMessages() {
  const res = await fetch("/api/messages?limit=50");
  const data = await res.json();
  chatEl.innerHTML = "";
  for (const msg of data.messages || []) {
    renderMessage(msg.role, msg.content);
  }
  showEmptyState();
}

function parseSseChunk(buffer) {
  const events = [];
  const parts = buffer.split("\n\n");
  const rest = parts.pop() || "";

  for (const part of parts) {
    if (!part.trim()) continue;
    let event = "message";
    let data = "";
    for (const line of part.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data = line.slice(5).trim();
    }
    if (data) {
      try {
        events.push({ event, data: JSON.parse(data) });
      } catch {
        /* ignore malformed */
      }
    }
  }
  return { events, rest };
}

async function consumeSseStream(res, handlers) {
  if (!res.ok || !res.body) {
    throw new Error("stream unavailable");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseChunk(buffer);
    buffer = parsed.rest;

    for (const { event, data } of parsed.events) {
      const handler = handlers[event];
      if (handler) handler(data);
    }
  }
}

async function sendMessage(text) {
  if (!text.trim() || streaming) return;

  clearEmptyState();
  renderMessage("user", text);
  resetInput();
  setBusy(true);
  setThinking(true);

  let crowleyBubble = null;
  let chatDone = false;

  try {
    await consumeSseStream(
      await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      }),
      {
        status: (data) => {
          if (data.phase === "thinking") {
            setBusy(true);
            setThinking(true);
          }
        },
        token: (data) => {
          hideThinking();
          if (!crowleyBubble) {
            crowleyBubble = renderMessage("assistant", "", "streaming");
          }
          const nextRaw = (crowleyBubble.dataset.raw || "") + (data.text || "");
          setMessageContent(crowleyBubble, nextRaw, { streaming: true });
          chatEl.scrollTop = chatEl.scrollHeight;
        },
        done: (data) => {
          chatDone = true;
          if (crowleyBubble) {
            crowleyBubble.classList.remove("streaming");
            const finalText = data.reply || crowleyBubble.dataset.raw || "";
            setMessageContent(crowleyBubble, finalText, { streaming: false });
          } else if (data.reply) {
            renderMessage("assistant", data.reply);
          }
          refreshPanels();
          scheduleExtractionRefresh();
        },
        error: (data) => {
          renderError(data.message || "Something went wrong.");
        },
      }
    );
  } catch {
    renderError("Could not reach Crowley.");
  } finally {
    setBusy(false);
    if (chatDone) {
      refreshPanels();
    }
  }
}

async function runDiagnostics() {
  if (streaming) return;

  clearEmptyState();
  setBusy(true);
  setThinking(true, "Preparing briefing");

  let diagBlock = null;
  let diagDone = false;

  try {
    await consumeSseStream(await fetch("/api/diagnostics"), {
      status: (data) => {
        if (data.phase === "thinking") {
          setBusy(true);
          setThinking(true, "Preparing briefing");
        }
      },
      token: (data) => {
        hideThinking();
        if (!diagBlock) {
          diagBlock = renderDiagnosticsBlock("", "streaming");
        }
        const nextRaw = (diagBlock.dataset.raw || "") + (data.text || "");
        setMessageContent(diagBlock, nextRaw, { streaming: true });
        chatEl.scrollTop = chatEl.scrollHeight;
      },
      done: (data) => {
        diagDone = true;
        if (diagBlock) {
          diagBlock.classList.remove("streaming");
          const finalText = data.reply || diagBlock.dataset.raw || "";
          setMessageContent(diagBlock, finalText, { streaming: false });
        } else if (data.reply) {
          renderDiagnosticsBlock(data.reply);
        }
        refreshPanels();
      },
      error: (data) => {
        renderError(data.message || "Diagnostics failed.");
      },
    });
  } catch {
    renderError("Could not run diagnostics.");
  } finally {
    setBusy(false);
    if (diagDone) {
      refreshPanels();
    }
  }
}

sendBtn.addEventListener("click", () => sendMessage(inputEl.value));

inputEl.addEventListener("input", autoGrowInput);

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage(inputEl.value);
  }
});

refreshBtn.addEventListener("click", () => {
  refreshPanels();
  loadHealth();
});

if (panelTicketsEl) {
  panelTicketsEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".ticket-done-btn");
    if (btn) {
      e.preventDefault();
      const ticketId = Number(btn.dataset.ticketId);
      if (ticketId) completeTicket(ticketId);
      return;
    }
    const row = e.target.closest("[data-ticket-id]");
    if (!row || !panelTicketsEl.contains(row)) return;
    const ticketId = Number(row.dataset.ticketId);
    if (ticketId) selectTicket(ticketId);
  });
}

if (panelTasksEl) {
  panelTasksEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".task-done-btn");
    if (!btn) return;
    e.preventDefault();
    const taskId = Number(btn.dataset.taskId);
    if (taskId) completeTask(taskId);
  });
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    refreshPanels();
    loadHealth();
  }
});

if (diagnosticsBtn) {
  diagnosticsBtn.addEventListener("click", () => runDiagnostics());
}
if (contextToggle) {
  contextToggle.addEventListener("click", () => toggleContextDrawer());
}
contextTabs.forEach((tab) => {
  tab.addEventListener("click", () => setContextTab(tab.dataset.tab));
});
if (memorySearchEl) {
  memorySearchEl.addEventListener("input", scheduleMemoryLoad);
}
[memorySourceEl, memoryTypeEl, memoryStatusEl, memoryLayerEl].forEach((el) => {
  if (el) el.addEventListener("change", () => loadMemoryItems());
});

autoGrowInput();
loadHealth();
loadMessages();
refreshPanels();
startLiveSync();
