const state = {
  dashboard: null,
  reports: [],
  selectedMonitorIds: [],
  expandedSwitcherIndex: null,
  selectedReportId: null,
  reportDetailCache: new Map(),
  activeView: "dashboard",
};

const elements = {
  dashboardView: document.getElementById("dashboardView"),
  reportsView: document.getElementById("reportsView"),
  monitors: document.getElementById("monitors"),
  refreshStamp: document.getElementById("refreshStamp"),
  reportsToggle: document.getElementById("reportsToggle"),
  reportsClose: document.getElementById("reportsClose"),
  reportsList: document.getElementById("reportsList"),
  reportDetail: document.getElementById("reportDetail"),
  monitorTemplate: document.getElementById("monitorTemplate"),
};
const DASHBOARD_POLL_INTERVAL_MS = 1000;

const AGENT_LABEL_MAP = {
  image_guardrail: {
    label: "Guardrail",
  },
  vlm_agent: {
    label: "VLM",
  },
  validator_agent: {
    label: "Validator",
  },
  orchestrator_agent: {
    label: "Orchestrator",
  },
  order_expert: {
    label: "Order Expert",
  },
  safety_expert: {
    label: "Safety Expert",
  },
  environment_expert: {
    label: "Environment Expert",
  },
  alert_manager: {
    label: "Alert Manager",
  },
};
const AGENT_STATUS_ORDER = [
  "image_guardrail",
  "vlm_agent",
  "validator_agent",
  "orchestrator_agent",
  "order_expert",
  "safety_expert",
  "environment_expert",
  "alert_manager",
];

async function bootstrap() {
  bindEvents();
  syncViewFromHash();
  await loadDashboard();

  window.setInterval(() => {
    loadDashboard({ silent: true });
  }, DASHBOARD_POLL_INTERVAL_MS);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      loadDashboard({ silent: true });
    }
  });
}

function bindEvents() {
  elements.reportsToggle.addEventListener("click", () => setView("reports"));
  elements.reportsClose.addEventListener("click", () => setView("dashboard"));
  window.addEventListener("hashchange", syncViewFromHash);

  elements.monitors.addEventListener("click", async (event) => {
    const toggle = event.target.closest("[data-monitor-toggle]");
    if (toggle) {
      const monitorIndex = Number(toggle.dataset.monitorToggle);
      state.expandedSwitcherIndex = state.expandedSwitcherIndex === monitorIndex ? null : monitorIndex;
      renderDashboard();
      return;
    }

    const button = event.target.closest("[data-camera-switch]");
    if (!button) {
      return;
    }

    const monitorIndex = Number(button.dataset.monitorIndex);
    try {
      await switchCamera(button.dataset.cameraSwitch, monitorIndex);
    } catch (error) {
      console.error(error);
      await loadDashboard();
    }
  });

  elements.reportsList.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-report-id]");
    if (!button) {
      return;
    }
    await selectReport(button.dataset.reportId);
  });
}

function syncViewFromHash() {
  if (window.location.hash === "#reports") {
    setView("reports", { updateHash: false });
    return;
  }
  setView("dashboard", { updateHash: false });
}

function setView(view, { updateHash = true } = {}) {
  state.activeView = view;
  const showingReports = view === "reports";

  elements.dashboardView.classList.toggle("view-hidden", showingReports);
  elements.reportsView.classList.toggle("view-hidden", !showingReports);
  elements.reportsView.hidden = !showingReports;

  if (updateHash) {
    if (showingReports) {
      window.location.hash = "reports";
    } else if (window.location.hash) {
      history.replaceState(null, "", window.location.pathname);
    }
  }

  if (showingReports) {
    loadReports();
  }
}

async function loadDashboard({ silent = false } = {}) {
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Dashboard API returned ${response.status}`);
    }

    state.dashboard = await response.json();
    repairSelectedMonitors();
    renderDashboard();
    renderRefreshStamp();
  } catch (error) {
    console.error(error);
    if (!silent) {
      renderDashboardError(error);
    }
  }
}

function repairSelectedMonitors() {
  const cameras = state.dashboard?.cameras ?? [];
  const defaults = state.dashboard?.default_monitor_ids ?? [];
  const preferredCameraId = defaults[0] ?? cameras[0]?.camera_id ?? "";
  state.selectedMonitorIds = preferredCameraId ? [preferredCameraId] : [];
}

function renderDashboard() {
  const cameras = state.dashboard?.cameras ?? [];
  if (!cameras.length) {
    elements.monitors.innerHTML = `<div class="empty-state">No cameras were found for the dashboard.</div>`;
    return;
  }

  const cameraMap = new Map(cameras.map((camera) => [camera.camera_id, camera]));
  const monitorIndex = 0;
  const cameraId = state.selectedMonitorIds[monitorIndex];
  const camera = cameraMap.get(cameraId) ?? cameras[monitorIndex] ?? cameras[0];
  const existingCard = elements.monitors.querySelector(".monitor-card");

  if (!existingCard) {
    elements.monitors.replaceChildren(buildMonitorCard(camera, monitorIndex, cameras));
    return;
  }

  populateMonitorCard(existingCard, camera, monitorIndex, cameras);
}

function buildMonitorCard(camera, monitorIndex, allCameras) {
  const node = elements.monitorTemplate.content.firstElementChild.cloneNode(true);
  populateMonitorCard(node, camera, monitorIndex, allCameras);
  return node;
}

function populateMonitorCard(node, camera, monitorIndex, allCameras) {
  const label = "Primary Monitor";
  const isSwitcherOpen = state.expandedSwitcherIndex === monitorIndex;
  node.dataset.cameraId = camera.camera_id;

  node.querySelector(".monitor-label").textContent = label;
  node.querySelector(".monitor-title").textContent = `Camera ${camera.camera_id} / ${camera.location_description}`;

  const chip = node.querySelector(".status-chip");
  chip.className = "status-chip";
  chip.textContent = camera.status_label;
  chip.classList.add(`is-${camera.status_level}`);
  node.querySelector(".agent-trace-strip").replaceChildren(...buildAgentStatusPills(camera));

  node.querySelector(".monitor-timestamp").textContent = `Analysis ${camera.last_analysis_at}`;
  node.querySelector(".incident-line").textContent = camera.status_summary_text;
  node.querySelector(".road-type").textContent = camera.road_type;
  node.querySelector(".dispatch-state").textContent = formatDispatch(camera);
  node.querySelector(".analysis-time").textContent = camera.last_analysis_at;
  node.querySelector(".alert-type").textContent = formatAlertType(camera);
  renderLog(
    node.querySelector(".status-log"),
    camera.status_history,
    buildStatusLogEntry,
    "No status events have been logged for this camera yet.",
  );
  renderLog(
    node.querySelector(".summary-log"),
    camera.analysis_history,
    buildAnalysisLogEntry,
    "No completed analysis has been logged for this camera yet.",
  );
  node.querySelector(".image-source").textContent = formatImageSource(camera.image_source);
  node.querySelector(".frame-timestamp").textContent = camera.last_frame_at;
  node.querySelector(".site-name").textContent = camera.location_description;
  node.querySelector(".site-area").textContent = camera.area_or_key_landmark;
  node.querySelector(".camera-count").textContent = `${allCameras.length} cameras loaded`;

  const toggleButton = node.querySelector(".camera-toggle-button");
  toggleButton.dataset.monitorToggle = String(monitorIndex);
  toggleButton.textContent = isSwitcherOpen ? "Close list" : "Switch camera";
  toggleButton.setAttribute("aria-expanded", isSwitcherOpen ? "true" : "false");

  const image = node.querySelector(".camera-frame");
  const placeholder = node.querySelector(".image-placeholder");
  const placeholderTitle = node.querySelector(".placeholder-title");
  const placeholderDetail = node.querySelector(".placeholder-detail");
  renderMonitorImage(image, placeholder, placeholderTitle, placeholderDetail, camera);

  node.querySelector(".signal-strip").replaceChildren(...buildSignalPills(camera));
  const cameraListPanel = node.querySelector(".camera-list-panel");
  cameraListPanel.hidden = !isSwitcherOpen;
  node.querySelector(".camera-list").replaceChildren(
    ...buildCameraButtons(allCameras, camera.camera_id, monitorIndex),
  );
}

function renderMonitorImage(image, placeholder, placeholderTitle, placeholderDetail, camera) {
  const candidates = Array.isArray(camera.image_candidates)
    ? camera.image_candidates.filter(Boolean)
    : camera.image_url
      ? [camera.image_url]
      : [];

  image.onload = () => {
    image.dataset.loadState = "loaded";
    image.dataset.resolvedUrl = image.dataset.pendingUrl || "";
    placeholder.hidden = true;
    image.hidden = false;
  };

  image.onerror = () => {
    const nextIndex = Number(image.dataset.candidateIndex || "0") + 1;
    if (nextIndex < candidates.length) {
      image.dataset.candidateIndex = String(nextIndex);
      loadImageCandidate(image, candidates[nextIndex]);
      return;
    }

    image.dataset.loadState = "error";
    image.dataset.resolvedUrl = "";
    applyPlaceholderState(placeholder, placeholderTitle, placeholderDetail, camera);
    image.hidden = true;
  };

  if (!candidates.length) {
    image.removeAttribute("src");
    image.dataset.canonicalUrl = "";
    image.dataset.loadState = "idle";
    image.dataset.resolvedUrl = "";
    image.alt = "";
    applyPlaceholderState(placeholder, placeholderTitle, placeholderDetail, camera);
    image.hidden = true;
    return;
  }

  const preferredUrl = candidates[0];
  const currentCanonicalUrl = image.dataset.canonicalUrl || "";
  const resolvedUrl = image.dataset.resolvedUrl || "";
  const loadState = image.dataset.loadState || "idle";

  image.alt = `Camera ${camera.camera_id} live frame`;

  if (currentCanonicalUrl === preferredUrl && resolvedUrl === preferredUrl && loadState === "loaded") {
    placeholder.hidden = true;
    image.hidden = false;
    return;
  }

  image.dataset.candidateIndex = "0";
  image.dataset.canonicalUrl = preferredUrl;
  image.dataset.loadState = "pending";
  loadImageCandidate(image, preferredUrl, loadState === "error");
}

function loadImageCandidate(image, url, forceRetry = false) {
  image.dataset.pendingUrl = url;
  const resolvedUrl = forceRetry ? appendClientRetryToken(url) : url;
  if (image.getAttribute("src") !== resolvedUrl) {
    image.src = resolvedUrl;
    return;
  }

  if (forceRetry) {
    image.src = appendClientRetryToken(url);
  }
}

function appendClientRetryToken(url) {
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}client_retry=${Date.now()}`;
}

function buildSignalPills(camera) {
  const signals = camera.signal_snapshot ?? {};
  const rows = [
    { label: "Vehicles", value: `${signals.vehicle_count ?? 0}` },
    { label: "Stopped", value: `${signals.stopped_vehicle_count ?? 0}` },
    { label: "Blocked lanes", value: `${signals.blocked_lanes ?? 0}` },
    { label: "Queueing", value: booleanLabel(signals.queueing) },
    { label: "Low visibility", value: booleanLabel(signals.low_visibility) },
    { label: "Water", value: booleanLabel(signals.water_present) },
  ];

  return rows.map((entry) => {
    const pill = document.createElement("span");
    pill.className = "signal-pill";
    if (entry.value === "YES" || Number(entry.value) > 0) {
      pill.classList.add("is-positive");
    }
    pill.innerHTML = `<span>${escapeHtml(entry.label)}</span><strong>${escapeHtml(entry.value)}</strong>`;
    return pill;
  });
}

function buildAgentStatusPills(camera) {
  const activeAgents = new Set(
    Array.isArray(camera.current_agents) ? camera.current_agents.filter(Boolean) : [],
  );

  return AGENT_STATUS_ORDER.map((agentName) => {
    const metadata = AGENT_LABEL_MAP[agentName] ?? {
      label: formatBackendStatus(agentName),
    };
    const item = document.createElement("span");
    item.className = "agent-status-pill";
    item.dataset.agent = agentName;
    if (activeAgents.has(agentName)) {
      item.classList.add("is-active");
    }
    item.setAttribute("aria-label", metadata.label);
    item.title = metadata.label;
    item.innerHTML = `
      <span class="agent-status-light" aria-hidden="true"></span>
      <span class="agent-status-text">${escapeHtml(metadata.label)}</span>
    `;
    return item;
  });
}

function renderLog(container, entries, buildEntry, emptyMessage) {
  const items = Array.isArray(entries) ? entries : [];
  const shouldStickToBottom =
    !container.dataset.hasRendered ||
    container.scrollHeight - container.scrollTop - container.clientHeight <= 24;
  const previousScrollTop = container.scrollTop;

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "log-empty";
    empty.textContent = emptyMessage;
    container.replaceChildren(empty);
  } else {
    container.replaceChildren(...items.map((entry, index) => buildEntry(entry, index === items.length - 1)));
  }

  container.dataset.hasRendered = "true";
  if (shouldStickToBottom) {
    container.scrollTop = container.scrollHeight;
    return;
  }

  const maxScrollTop = Math.max(container.scrollHeight - container.clientHeight, 0);
  container.scrollTop = Math.min(previousScrollTop, maxScrollTop);
}

function buildStatusLogEntry(entry, isLatest) {
  const item = document.createElement("article");
  item.className = "log-entry";
  if (isLatest || entry.is_current) {
    item.classList.add("is-current");
  }

  const label = entry.label || formatBackendStatus(entry.backend_status);
  item.innerHTML = `
    <div class="log-entry-meta">
      <span class="log-entry-label">${escapeHtml(label)}</span>
      <time>${escapeHtml(entry.timestamp || "Recent")}</time>
    </div>
    <p>${escapeHtml(entry.message || "")}</p>
  `;
  return item;
}

function buildAnalysisLogEntry(entry, isLatest) {
  const item = document.createElement("article");
  item.className = "log-entry";
  if (isLatest || entry.is_current) {
    item.classList.add("is-current");
  }

  const tags = [];
  if (entry.severity) {
    tags.push(`<span class="log-entry-tag">${escapeHtml(entry.severity.toUpperCase())}</span>`);
  }
  if (entry.emergency_type) {
    tags.push(`<span class="log-entry-tag">${escapeHtml(entry.emergency_type)}</span>`);
  }

  item.innerHTML = `
    <div class="log-entry-meta">
      <time>${escapeHtml(entry.timestamp || "Recent")}</time>
      <div class="log-entry-tags">${tags.join("")}</div>
    </div>
    <p>${escapeHtml(entry.summary || "")}</p>
  `;
  return item;
}

function buildCameraButtons(allCameras, selectedCameraId, monitorIndex) {
  return allCameras.map((camera) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "camera-button";
    if (camera.camera_id === selectedCameraId) {
      button.classList.add("is-selected");
    }
    button.dataset.cameraSwitch = camera.camera_id;
    button.dataset.monitorIndex = String(monitorIndex);
    button.innerHTML = `
      <strong>${escapeHtml(`Camera ${camera.camera_id}`)}</strong>
      <span>${escapeHtml(camera.road_type)} / ${escapeHtml(camera.area_or_key_landmark)}</span>
    `;
    return button;
  });
}

function renderDashboardError(error) {
  elements.monitors.innerHTML = `
    <div class="empty-state">
      <strong>Dashboard data is unavailable.</strong>
      <p>${escapeHtml(error.message)}</p>
    </div>
  `;
}

function applyPlaceholderState(placeholder, titleNode, detailNode, camera) {
  const copy = formatPlaceholderCopy(camera);
  titleNode.textContent = copy.title;
  detailNode.textContent = copy.detail;
  placeholder.hidden = false;
}

function renderRefreshStamp() {
  const generatedAt = state.dashboard?.generated_at;
  elements.refreshStamp.textContent = generatedAt
    ? `Last refresh ${formatShortTimestamp(generatedAt)}`
    : "Waiting for dashboard telemetry";
}

async function switchCamera(cameraId, monitorIndex) {
  state.selectedMonitorIds[monitorIndex] = cameraId;
  state.expandedSwitcherIndex = null;
  renderDashboard();

  const response = await fetch("/api/runtime/select-camera", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ camera_id: cameraId }),
  });

  if (!response.ok) {
    throw new Error(`Camera switch API returned ${response.status}`);
  }

  state.dashboard = await response.json();
  repairSelectedMonitors();
  renderDashboard();
  renderRefreshStamp();
}

async function loadReports() {
  try {
    const response = await fetch("/api/reports", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Reports API returned ${response.status}`);
    }

    const payload = await response.json();
    state.reports = payload.reports ?? [];
    renderReportsList();

    if (!state.reports.length) {
      renderEmptyReportState("No daily reports are available yet.");
      return;
    }

    const preferredReportId =
      state.selectedReportId && state.reports.some((report) => report.report_id === state.selectedReportId)
        ? state.selectedReportId
        : state.reports[0].report_id;
    await selectReport(preferredReportId);
  } catch (error) {
    console.error(error);
    elements.reportsList.innerHTML = `<div class="empty-state">Failed to load report history.</div>`;
    renderEmptyReportState(error.message);
  }
}

function renderReportsList() {
  if (!state.reports.length) {
    elements.reportsList.innerHTML = `<div class="empty-state">No report archive found.</div>`;
    return;
  }

  const region = document.createElement("div");
  region.className = "scroll-region";

  state.reports.forEach((report) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "report-button";
    if (report.report_id === state.selectedReportId) {
      button.classList.add("is-selected");
    }
    button.dataset.reportId = report.report_id;
    button.innerHTML = `
      <strong>${escapeHtml(report.title)}</strong>
      <span>${escapeHtml(report.updated_at)}</span>
      <span>${escapeHtml(report.excerpt)}</span>
    `;
    region.appendChild(button);
  });

  elements.reportsList.replaceChildren(region);
}

async function selectReport(reportId) {
  state.selectedReportId = reportId;
  renderReportsList();

  if (!state.reportDetailCache.has(reportId)) {
    const response = await fetch(`/api/reports/${encodeURIComponent(reportId)}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Report detail API returned ${response.status}`);
    }
    state.reportDetailCache.set(reportId, await response.json());
  }

  renderReportDetail(state.reportDetailCache.get(reportId));
}

function renderReportDetail(report) {
  if (!report) {
    renderEmptyReportState("Select a report to inspect its contents.");
    return;
  }

  elements.reportDetail.innerHTML = `
    <div class="report-heading">
      <p class="eyebrow">REPORT / ${escapeHtml(report.report_id)}</p>
      <h3>${escapeHtml(report.title)}</h3>
      <div class="report-meta">
        ${renderReportMetaPill("Updated", report.updated_at)}
        ${renderReportMetaPill("Words", String(report.word_count))}
      </div>
    </div>
    <div class="report-markdown">${markdownToHtml(report.content)}</div>
  `;
}

function renderEmptyReportState(message) {
  elements.reportDetail.innerHTML = `
    <div class="report-detail-empty">
      <div>
        <p class="eyebrow">REPORT VIEWER</p>
        <p>${escapeHtml(message)}</p>
      </div>
    </div>
  `;
}

function renderReportMetaPill(label, value) {
  return `<span class="report-meta-pill"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></span>`;
}

function markdownToHtml(markdown) {
  const lines = markdown.replace(/\r/g, "").split("\n");
  const html = [];
  const paragraph = [];
  const blockquote = [];
  const table = [];
  let inUl = false;
  let inOl = false;

  function flushParagraph() {
    if (!paragraph.length) {
      return;
    }
    html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
    paragraph.length = 0;
  }

  function flushBlockquote() {
    if (!blockquote.length) {
      return;
    }
    html.push(`<blockquote>${renderInline(blockquote.join(" "))}</blockquote>`);
    blockquote.length = 0;
  }

  function flushTable() {
    if (!table.length) {
      return;
    }

    const rows = table
      .filter((row, index) => !(index === 1 && /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?$/.test(row)))
      .map(parseTableRow);
    if (!rows.length) {
      table.length = 0;
      return;
    }

    const [head, ...body] = rows;
    const headHtml = `<thead><tr>${head.map((cell) => `<th>${renderInline(cell)}</th>`).join("")}</tr></thead>`;
    const bodyHtml = body.length
      ? `<tbody>${body.map((row) => `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join("")}</tr>`).join("")}</tbody>`
      : "";
    html.push(`<table>${headHtml}${bodyHtml}</table>`);
    table.length = 0;
  }

  function closeLists() {
    if (inUl) {
      html.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      html.push("</ol>");
      inOl = false;
    }
  }

  lines.forEach((rawLine) => {
    const line = rawLine.trim();

    if (!line) {
      flushParagraph();
      flushBlockquote();
      flushTable();
      closeLists();
      return;
    }

    if (line.startsWith("|")) {
      flushParagraph();
      flushBlockquote();
      closeLists();
      table.push(line);
      return;
    }

    flushTable();

    if (line.startsWith(">")) {
      flushParagraph();
      closeLists();
      blockquote.push(line.replace(/^>\s?/, ""));
      return;
    }

    flushBlockquote();

    if (/^###\s+/.test(line)) {
      flushParagraph();
      closeLists();
      html.push(`<h3>${renderInline(line.replace(/^###\s+/, ""))}</h3>`);
      return;
    }

    if (/^##\s+/.test(line)) {
      flushParagraph();
      closeLists();
      html.push(`<h2>${renderInline(line.replace(/^##\s+/, ""))}</h2>`);
      return;
    }

    if (/^#\s+/.test(line)) {
      flushParagraph();
      closeLists();
      html.push(`<h1>${renderInline(line.replace(/^#\s+/, ""))}</h1>`);
      return;
    }

    if (/^- /.test(line)) {
      flushParagraph();
      if (inOl) {
        html.push("</ol>");
        inOl = false;
      }
      if (!inUl) {
        html.push("<ul>");
        inUl = true;
      }
      html.push(`<li>${renderInline(line.replace(/^- /, ""))}</li>`);
      return;
    }

    if (/^\d+\.\s+/.test(line)) {
      flushParagraph();
      if (inUl) {
        html.push("</ul>");
        inUl = false;
      }
      if (!inOl) {
        html.push("<ol>");
        inOl = true;
      }
      html.push(`<li>${renderInline(line.replace(/^\d+\.\s+/, ""))}</li>`);
      return;
    }

    closeLists();
    paragraph.push(line);
  });

  flushParagraph();
  flushBlockquote();
  flushTable();
  closeLists();

  return html.join("");
}

function parseTableRow(line) {
  return line
    .split("|")
    .slice(1, -1)
    .map((cell) => cell.trim());
}

function renderInline(text) {
  return escapeHtml(text)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDispatch(camera) {
  if (camera.dispatch_status) {
    const targets = camera.dispatch_targets?.length ? ` / ${camera.dispatch_targets.join(", ")}` : "";
    return `${camera.dispatch_status.toUpperCase()}${targets}`;
  }
  return "Standby";
}

function formatAlertType(camera) {
  if (!camera.emergency_type) {
    return camera.status_level === "blocked" ? "Guardrail block" : "No active alert";
  }
  const severity = camera.severity ? ` / ${camera.severity.toUpperCase()}` : "";
  return `${camera.emergency_type}${severity}`;
}

function formatImageSource(imageSource) {
  if (imageSource === "approved_frame") {
    return "Guardrail-approved frame";
  }
  if (imageSource === "approved_frame_pending") {
    return "Awaiting guardrail approval";
  }
  if (imageSource === "local_frame") {
    return "Local cached frame";
  }
  if (imageSource === "live_feed") {
    return "Remote live feed";
  }
  return "Unavailable";
}

function formatPlaceholderCopy(camera) {
  if (camera.image_source === "approved_frame_pending") {
    return {
      title: "Awaiting approved frame",
      detail: "The latest frame is still being checked before it can be shown on the monitor.",
    };
  }
  if (camera.backend_status === "processing" || camera.backend_status === "fetching" || camera.backend_status === "starting") {
    return {
      title: "Preparing monitor frame",
      detail: "The backend is fetching or validating the latest image for this camera.",
    };
  }
  if (camera.backend_status === "fetch_error") {
    return {
      title: "Camera fetch failed",
      detail: camera.status_detail || "The selected camera did not return a usable frame.",
    };
  }
  return {
    title: "Feed unavailable",
    detail: "No local frame or live image could be resolved for the selected camera.",
  };
}

function booleanLabel(value) {
  return value ? "YES" : "NO";
}

function formatBackendStatus(value) {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return "Update";
  }
  return normalized
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatShortTimestamp(isoValue) {
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) {
    return isoValue;
  }
  return date.toLocaleString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

bootstrap();
