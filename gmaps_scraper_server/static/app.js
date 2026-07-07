import { initIcons, icon } from "./icons.js?v=2";

const PAGE_SIZE = 25;

const CITY_LABELS = {
  Dammam: "الدمام",
  Riyadh: "الرياض",
  Jeddah: "جدة",
  Khobar: "الخبر",
  Mecca: "مكة",
  Medina: "المدينة المنورة",
  Abha: "أبها",
  Tabuk: "تبوك",
};

function cityLabel(name) {
  return CITY_LABELS[name] || name || "—";
}

function formatStatsLine(stats) {
  const total = stats.total ?? 0;
  const shared = stats.whatsapp_shared ?? 0;
  const pending = stats.whatsapp_pending ?? 0;
  const phone = stats.with_phone ?? 0;
  return `${total} إجمالي · ${shared} مشترك · ${pending} متبقٍ · ${phone} بها هاتف`;
}

function formatPagination(page, totalPages, total) {
  return `صفحة ${page} من ${totalPages} · ${total} مكان`;
}

const form = document.getElementById("scrape-form");
const statusEl = document.getElementById("status");
const submitBtn = document.getElementById("submit-btn");
const submitLabel = document.getElementById("submit-label");
const singlePanel = document.getElementById("single-panel");
const cityPanel = document.getElementById("city-panel");
const progressWrap = document.getElementById("progress-wrap");
const progressFill = document.getElementById("progress-fill");
const progressText = document.getElementById("progress-text");
const savedTableBody = document.querySelector("#saved-table tbody");
const resultsStatsLine = document.getElementById("results-stats-line");
const dbCountBadge = document.getElementById("db-count-badge");
const downloadCsvBtn = document.getElementById("download-csv");
const downloadJsonBtn = document.getElementById("download-json");
const pagePrevBtn = document.getElementById("page-prev");
const pageNextBtn = document.getElementById("page-next");
const pageInfoEl = document.getElementById("page-info");
const toastEl = document.getElementById("toast");
const resultsPanel = document.getElementById("results-panel");

let currentMode = "single";
let savedPlaces = [];
let currentPage = 1;
let pagination = { page: 1, page_size: PAGE_SIZE, total: 0, total_pages: 1 };
let pollTimer = null;
let toastTimer = null;
let sharingIds = new Set();
let selectedIds = new Set();
let loadInFlight = false;
let scrapeActive = false;

const scrapeLogWrap = document.getElementById("scrape-log-wrap");
const scrapeLogScroll = document.getElementById("scrape-log-scroll");
const scrapeLogEl = document.getElementById("scrape-log");
const stopJobBtn = document.getElementById("stop-job-btn");
let jobWatchAbort = null;
let jobEventCursor = 0;
let scrapeLogPinnedBottom = true;
const JOB_POLL_MS = 2000;

function isScrapeLogAtBottom(threshold = 28) {
  if (!scrapeLogScroll) return true;
  return scrapeLogScroll.scrollHeight - scrapeLogScroll.scrollTop - scrapeLogScroll.clientHeight <= threshold;
}

function scrollScrapeLogToBottom(force = false) {
  if (!scrapeLogScroll) return;
  if (force || scrapeLogPinnedBottom) {
    scrapeLogScroll.scrollTop = scrapeLogScroll.scrollHeight;
    scrapeLogPinnedBottom = true;
  }
}

if (scrapeLogScroll) {
  scrapeLogScroll.addEventListener("scroll", () => {
    scrapeLogPinnedBottom = isScrapeLogAtBottom();
  }, { passive: true });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const bulkBar = document.getElementById("bulk-bar");
const bulkCountEl = document.getElementById("bulk-count");
const selectAllPageCb = document.getElementById("select-all-page");

void initIcons();

function showLoadError(err) {
  const msg = err?.message || "تعذّر تحميل البيانات";
  resultsStatsLine.textContent = `خطأ في التحميل — ${msg}`;
  showToast("تعذّر تحميل النتائج — حاول تحديث الصفحة");
}

function showToast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.add("hidden"), 2800);
}

function isResultsVisible() {
  return !resultsPanel.classList.contains("hidden");
}

function startLivePoll() {
  stopLivePoll();
  document.getElementById("live-indicator").classList.remove("hidden");
  pollTimer = setInterval(() => {
    if (isResultsVisible() && sharingIds.size === 0 && !scrapeActive) {
      loadSavedPlaces({ silent: true });
    }
  }, 3000);
}

function stopLivePoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  document.getElementById("live-indicator").classList.add("hidden");
}

document.querySelectorAll(".main-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".main-tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
    document.getElementById(tab.dataset.panel).classList.remove("hidden");
    if (tab.dataset.panel === "results-panel") {
      loadSavedPlaces();
      startLivePoll();
    } else {
      stopLivePoll();
    }
  });
});

document.querySelectorAll(".mode-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    currentMode = tab.dataset.mode;
    document.querySelectorAll(".mode-tab").forEach((t) => t.classList.toggle("active", t === tab));
    singlePanel.classList.toggle("hidden", currentMode !== "single");
    cityPanel.classList.toggle("hidden", currentMode !== "city");
    submitLabel.textContent = currentMode === "city" ? "مسح المدينة كاملة" : "بدء الجمع";
  });
});

document.querySelectorAll(".preset").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.getElementById("query").value = btn.dataset.query;
    if (/[\u0600-\u06FF]/.test(btn.dataset.query)) {
      document.getElementById("lang").value = "ar";
    }
  });
});

function setStatus(message, type) {
  statusEl.textContent = message;
  statusEl.className = `status ${type}`;
  statusEl.classList.remove("hidden");
}

function setProgress(step, total, message) {
  progressWrap.classList.remove("hidden");
  progressFill.style.width = `${total > 0 ? Math.round((step / total) * 100) : 0}%`;
  progressText.textContent = message || `منطقة ${step} / ${total}`;
}

function hideProgress() {
  progressWrap.classList.add("hidden");
  progressFill.style.width = "0%";
}

function clearScrapeLog() {
  scrapeLogEl.innerHTML = "";
  scrapeLogPinnedBottom = true;
  scrapeLogWrap.classList.add("hidden");
}

function appendScrapeLog(message, level = "info", ts = null) {
  scrapeLogWrap.classList.remove("hidden");
  const li = document.createElement("li");
  const time = (ts ? new Date(ts * 1000) : new Date()).toLocaleTimeString("ar-SA", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  li.className = `log-${level}`;
  li.innerHTML = `<time>${time}</time>${escapeHtml(message)}`;
  scrapeLogEl.appendChild(li);
  requestAnimationFrame(() => scrollScrapeLogToBottom());
}

function updateJobUI(running, status = {}) {
  scrapeActive = running;
  submitBtn.disabled = running;
  stopJobBtn.classList.toggle("hidden", !running);
  stopJobBtn.disabled = !running;
  if (running && status.label) {
    setStatus(`جاري التنفيذ: ${status.label}`, "loading");
  }
}

function saveTotalsSuffix(totals) {
  if (!totals) return "";
  const ins = totals.inserted ?? 0;
  const upd = totals.updated ?? 0;
  if (ins === 0 && upd === 0) return "";
  return ` · محفوظ: ${ins} جديد، ${upd} محدّث`;
}

function formatJobLogMessage(event) {
  if (!event) return "";
  if (event.type === "place_fetched" && event.place_name) {
    const idx = event.detail_index && event.detail_total
      ? `[${event.detail_index}/${event.detail_total}] `
      : "";
    const kind = event.place_kind ? `${event.place_kind}: ` : "";
    let line = `${idx}${kind}${event.place_name}`;
    if (event.place_phone) line += ` · ${event.place_phone}`;
    else line += " · بدون هاتف";
    line += saveTotalsSuffix(event.save_totals);
    if (event.step && event.total_steps) {
      line += ` · منطقة ${event.step}/${event.total_steps}`;
    }
    return line;
  }
  let msg = event.message || "";
  if (event.links_found && !msg.includes("القائمة")) {
    msg += ` · ${event.links_found} في القائمة`;
  }
  msg += saveTotalsSuffix(event.save_totals);
  return msg;
}

function logJobEvent(event) {
  const text = formatJobLogMessage(event);
  if (!text) return;
  const level =
    event.type === "error" ? "error"
    : event.type === "warning" || event.type === "cancelled" ? "warn"
    : event.type === "place_fetched" && !event.has_phone ? "warn"
    : event.type === "complete" || event.type === "start" || event.type === "cell_complete" ? "ok"
    : event.type === "place_fetched" ? "info"
    : "info";
  appendScrapeLog(text, level, event.ts);
}

function handleJobEvent(event, handlers, { quiet = false } = {}) {
  if (event.type === "idle" || event.type === "heartbeat" || event.type === "_end") return null;
  if (!quiet && ["start", "progress", "place_fetched", "cell_complete", "warning", "error", "complete", "cancelled"].includes(event.type)) {
    logJobEvent(event);
    if (event.type === "cell_complete" && event.save_stats?.ok) {
      const s = event.save_stats;
      const cellLine = `هذه المنطقة: +${s.inserted ?? 0} جديد، ${s.updated ?? 0} محدّث`;
      appendScrapeLog(cellLine, "ok", event.ts);
    } else if (event.type === "cell_complete" && event.save_stats?.ok === false) {
      appendScrapeLog(`خطأ الحفظ: ${event.save_stats.error || "unknown"}`, "error", event.ts);
    }
  }
  if (event.type === "start") handlers.onStart?.(event);
  else if (event.type === "progress" || event.type === "place_fetched" || event.type === "cell_complete" || event.type === "warning") handlers.onProgress?.(event);
  else if (event.type === "error") throw new Error(event.message || "فشل الجمع");
  else if (event.type === "complete" || event.type === "cancelled") {
    handlers.onComplete?.(event);
    return event;
  }
  return null;
}

async function fetchJobEvents(after) {
  const res = await fetch(`/api/job/events?after=${after}`);
  if (!res.ok) throw new Error(formatFetchError(new Error(`HTTP ${res.status}`), res));
  return res.json();
}

async function watchJob(handlers, { replay = false } = {}) {
  if (jobWatchAbort) jobWatchAbort.abort();
  jobWatchAbort = new AbortController();
  if (replay) jobEventCursor = 0;

  let reconnectNoteShown = false;

  while (!jobWatchAbort.signal.aborted) {
    let data;
    try {
      data = await fetchJobEvents(jobEventCursor);
      reconnectNoteShown = false;
    } catch (err) {
      if (jobWatchAbort.signal.aborted) return null;
      if (!reconnectNoteShown) {
        appendScrapeLog("انقطع الاتصال مؤقتاً — إعادة المزامنة…", "warn");
        reconnectNoteShown = true;
      }
      await sleep(JOB_POLL_MS);
      continue;
    }

    for (const event of data.events || []) {
      const result = handleJobEvent(event, handlers);
      if (result) return result;
    }
    jobEventCursor = data.total ?? jobEventCursor;

    if (data.running) {
      updateJobUI(true, data);
      if (data.step != null && data.total_steps) {
        setProgress(data.step, data.total_steps, data.message || "جاري التنفيذ…");
      } else if (data.message) {
        setProgress(0, 1, data.message);
      }
      await sleep(JOB_POLL_MS);
      continue;
    }

    const terminal = (data.events || []).slice().reverse().find((e) =>
      ["complete", "cancelled", "error"].includes(e.type)
    );
    if (terminal) {
      handlers.onComplete?.(terminal);
      return terminal;
    }
    return null;
  }
  return null;
}

async function startJob(url, body, handlers) {
  if (jobWatchAbort) jobWatchAbort.abort();
  jobEventCursor = 0;
  clearScrapeLog();
  progressWrap.classList.remove("hidden");
  setProgress(0, 1, "جاري البدء…");

  const startRes = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch((err) => {
    throw new Error(formatFetchError(err));
  });

  if (!startRes.ok) {
    const err = await startRes.json().catch(() => ({}));
    throw new Error(formatFetchError(new Error(err.detail || "فشل بدء العملية"), startRes));
  }

  const job = await startRes.json();
  updateJobUI(true, job);
  return watchJob(handlers);
}

function finishJobUI(event) {
  updateJobUI(false);
  hideProgress();
  if (jobWatchAbort) {
    jobWatchAbort.abort();
    jobWatchAbort = null;
  }
  if (!event) return;

  if (event.type === "cancelled") {
    setStatus(event.message || "تم إيقاف العملية", "error");
    return;
  }

  if (event.type === "complete") {
    const n = event.results_count ?? event.stats?.unique_count ?? 0;
    const saved = event.save_stats;
    let msg = event.message || `تم — ${n} مكان`;
    if (saved?.ok === false) {
      msg += ` · خطأ الحفظ: ${saved.error || "unknown"}`;
    } else if (saved && saved.ok !== false) {
      msg += ` · قاعدة البيانات: ${saved.inserted ?? 0} جديد، ${saved.updated ?? 0} محدّث`;
    }
    if (event.kind === "single" && n === 0) msg += " — تحقق من السجل (قد تكون صفحة موافقة Google)";
    setStatus(msg, n > 0 && saved?.ok !== false ? "success" : saved?.ok === false ? "error" : n > 0 ? "success" : "error");
    currentPage = 1;
    switchToResultsTab();
  }
}

const singleJobHandlers = {
  onStart: () => setProgress(0, 1, "بدء الجمع…"),
  onProgress: (e) => {
    if (e.detail_index && e.detail_total) {
      setProgress(e.detail_index, e.detail_total, formatJobLogMessage(e));
    } else if (e.found) {
      setProgress(0, 1, `تم العثور على ${e.found} رابط…${saveTotalsSuffix(e.save_totals)}`);
    } else {
      setProgress(0, 1, formatJobLogMessage(e) || "جاري التنفيذ…");
    }
  },
  onComplete: () => {},
};

const cityJobHandlers = {
  onStart: (e) => setProgress(0, e.total_steps || 1, e.message),
  onProgress: (e) => {
    if (e.step && e.total_steps) {
      if (e.type === "place_fetched" && e.detail_index && e.detail_total) {
        setProgress(e.step, e.total_steps, formatJobLogMessage(e));
      } else {
        setProgress(e.step, e.total_steps, formatJobLogMessage(e) || e.message);
      }
    } else if (e.detail_index && e.detail_total) {
      setProgress(e.detail_index, e.detail_total, formatJobLogMessage(e));
    }
    if (isResultsVisible() && (e.type === "cell_complete" || (e.type === "place_fetched" && e.detail_index % 15 === 0))) {
      loadSavedPlaces({ silent: true });
    }
  },
  onComplete: () => {},
};

function formatFetchError(err, res = null) {
  const msg = String(err?.message || err || "");
  if (msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("Load failed")) {
    if (res?.status === 504) return "انتهت مهلة الخادم — الجمع يستغرق وقتاً طويلاً. حاول مرة أخرى أو قلّل النتائج.";
    return "خطأ شبكة — انقطع الاتصال بالخادم. تحقق من الإنترنت أو أعد المحاولة.";
  }
  if (res?.status === 502 || res?.status === 503) return "الخادم غير متاح مؤقتاً (502/503) — انتظر وأعد المحاولة.";
  if (res?.status === 504) return "انتهت مهلة الخادم بعد 5 دقائق.";
  return msg || "حدث خطأ غير متوقع";
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function switchToResultsTab() {
  document.querySelector('.main-tab[data-panel="results-panel"]').click();
}

function buildQueryParams(forExport = false) {
  const status = document.getElementById("filter-status").value;
  const city = document.getElementById("filter-city").value;
  const search = document.getElementById("filter-search").value.trim();
  const params = new URLSearchParams();
  if (status === "shared") params.set("shared", "true");
  if (status === "pending") params.set("shared", "false");
  if (city) params.set("city", city);
  if (search) params.set("search", search);
  if (forExport) {
    params.set("all_rows", "true");
  } else {
    params.set("page", String(currentPage));
    params.set("page_size", String(PAGE_SIZE));
  }
  return params;
}

async function scrapeSingle() {
  const query = document.getElementById("query").value.trim();
  if (!query) throw new Error("أدخل كلمة البحث");
  const maxPlaces = parseInt(document.getElementById("max-places").value, 10) || 120;
  const lang = document.getElementById("lang").value;

  const event = await startJob("/api/job/scrape", {
    query, max_places: maxPlaces, lang,
    headless: true, concurrency: 5, dedupe: true, save_to_db: true,
  }, singleJobHandlers);
  finishJobUI(event);
}

async function scrapeCityStream() {
  const city = document.getElementById("city").value;
  const keyword = document.getElementById("city-keyword").value.trim() || null;
  const lang = document.getElementById("city-lang").value;
  const zoom = parseInt(document.getElementById("zoom").value, 10) || 15;
  const cellSize = parseFloat(document.getElementById("cell-size").value) || 4;
  const includeVet = document.getElementById("include-vet").checked;

  const event = await startJob("/api/job/scrape-city", {
    city, keyword, lang, zoom, cell_size_km: cellSize,
    max_per_cell: 120, headless: true, concurrency: 5,
    include_vet_clinics: includeVet, save_to_db: true,
  }, cityJobHandlers);
  finishJobUI(event);
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    if (currentMode === "city") await scrapeCityStream();
    else await scrapeSingle();
  } catch (err) {
    finishJobUI(null);
    const msg = formatFetchError(err);
    if (!msg.toLowerCase().includes("abort")) {
      appendScrapeLog(msg, "error");
      setStatus(msg, "error");
    }
  }
});

stopJobBtn.addEventListener("click", async () => {
  stopJobBtn.disabled = true;
  appendScrapeLog("طلب إيقاف العملية…", "warn");
  try {
    await fetch("/api/job/stop", { method: "POST" });
  } catch {
    appendScrapeLog("تعذّر إرسال طلب الإيقاف", "error");
    stopJobBtn.disabled = false;
  }
});

async function tryReconnectActiveJob() {
  try {
    const status = await fetch("/api/job/status").then((r) => r.json());
    if (!status.id || status.status === "idle") return;

    scrapeLogWrap.classList.remove("hidden");
    if (status.running) {
      document.querySelector('.main-tab[data-panel="scrape-panel"]')?.click();
      updateJobUI(true, status);
      setProgress(status.step || 0, status.total_steps || 1, status.message || "جاري التنفيذ…");
    } else {
      appendScrapeLog(`آخر عملية: ${status.label} (${status.status})`, "info");
    }

    const handlers = status.kind === "city" ? cityJobHandlers : singleJobHandlers;
    const event = await watchJob(handlers, { replay: true });
    scrollScrapeLogToBottom(true);
    finishJobUI(event);
  } catch (err) {
    if (err.name !== "AbortError") {
      updateJobUI(false);
      const msg = formatFetchError(err);
      if (!scrapeActive) appendScrapeLog(msg, "error");
    }
  }
}

function flattenPlace(p) {
  return {
    ...p,
    latitude: p.latitude ?? "",
    longitude: p.longitude ?? "",
    categories: Array.isArray(p.categories) ? p.categories.join(" | ") : p.categories ?? "",
    hours: Array.isArray(p.hours) ? p.hours.join(" | ") : p.hours ?? "",
  };
}

function toCsv(rows) {
  if (!rows.length) return "";
  const flat = rows.map(flattenPlace);
  const keys = [];
  flat.forEach((row) => Object.keys(row).forEach((k) => { if (!keys.includes(k)) keys.push(k); }));
  const esc = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [keys.join(","), ...flat.map((r) => keys.map((k) => esc(r[k])).join(","))].join("\n");
}

function downloadFile(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function buildWhatsAppDesktopUrl(place) {
  if (place.whatsapp_desktop_url) return place.whatsapp_desktop_url;
  if (place.whatsapp_phone && place.whatsapp_message) {
    return `whatsapp://send?phone=${place.whatsapp_phone}&text=${encodeURIComponent(place.whatsapp_message)}`;
  }
  return null;
}

function isMobileDevice() {
  return /Android|iPhone|iPad|iPod|webOS|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
    || (navigator.maxTouchPoints > 1 && window.innerWidth < 900);
}

function buildWhatsAppUrl(place) {
  if (isMobileDevice() && place.whatsapp_url) return place.whatsapp_url;
  return buildWhatsAppDesktopUrl(place);
}

function openWhatsAppApp(url) {
  // Must run synchronously from the click handler so macOS opens the WhatsApp app (whatsapp://).
  window.location.assign(url);
}

async function markShared(id) {
  const res = await fetch(`/api/places/${id}/whatsapp-shared`, { method: "POST" });
  if (!res.ok) throw new Error("تعذّر تعليم المشاركة");
  return res.json();
}

function patchPlaceInList(id, patch) {
  const idx = savedPlaces.findIndex((p) => p.id === id);
  if (idx >= 0) savedPlaces[idx] = { ...savedPlaces[idx], ...patch };
}

function applySharedLocally(placeId) {
  patchPlaceInList(placeId, {
    whatsapp_shared: true,
    whatsapp_shared_at: new Date().toISOString(),
  });
  renderSavedTable(savedPlaces, placeId);
  bumpSharedStats();
  bumpSharedAnalytics();
}

async function refreshStatsOnly() {
  const res = await fetch("/api/places/stats");
  if (!res.ok) return;
  const stats = await res.json();
  dbCountBadge.textContent = String(stats.total ?? 0);
  resultsStatsLine.textContent = formatStatsLine(stats);
  updateStatCards(stats);
}

async function openWhatsApp(place) {
  const url = buildWhatsAppUrl(place);
  if (!url) {
    alert("لا يوجد رقم هاتف لهذا المكان.");
    return;
  }

  openWhatsAppApp(url);

  sharingIds.add(place.id);
  applySharedLocally(place.id);
  showToast("تم فتح واتساب · وُسِم كمُشارَك ✓");

  try {
    const updated = await markShared(place.id);
    patchPlaceInList(place.id, updated);

    const filterStatus = document.getElementById("filter-status").value;
    if (filterStatus === "pending") {
      savedPlaces = savedPlaces.filter((p) => p.id !== place.id);
      pagination.total = Math.max(0, pagination.total - 1);
      pagination.total_pages = Math.max(1, Math.ceil(pagination.total / PAGE_SIZE));
      if (savedPlaces.length === 0 && currentPage > 1) currentPage -= 1;
      updatePaginationUI();
      renderSavedTable(savedPlaces);
      if (savedPlaces.length === 0) await loadSavedPlaces({ silent: true });
    } else {
      renderSavedTable(savedPlaces, place.id);
    }

    await refreshStatsOnly();
  } catch {
    patchPlaceInList(place.id, { whatsapp_shared: false, whatsapp_shared_at: null });
    renderSavedTable(savedPlaces);
    showToast("تعذّر الحفظ — حاول مرة أخرى");
    await refreshStatsOnly();
  } finally {
    sharingIds.delete(place.id);
  }
}

function bumpSharedStats() {
  const total = parseInt(document.getElementById("stat-total").textContent, 10) || 0;
  const shared = parseInt(document.getElementById("stat-shared").textContent, 10) || 0;
  const pending = parseInt(document.getElementById("stat-pending").textContent, 10) || 0;
  const phone = parseInt(document.getElementById("stat-phone").textContent, 10) || 0;
  document.getElementById("stat-shared").textContent = String(shared + 1);
  document.getElementById("stat-pending").textContent = String(Math.max(0, pending - 1));
  resultsStatsLine.textContent = formatStatsLine({
    total,
    whatsapp_shared: shared + 1,
    whatsapp_pending: Math.max(0, pending - 1),
    with_phone: phone,
  });
}

function updateStatCards(stats) {
  document.getElementById("stat-total").textContent = stats.total ?? 0;
  document.getElementById("stat-shared").textContent = stats.whatsapp_shared ?? 0;
  document.getElementById("stat-pending").textContent = stats.whatsapp_pending ?? 0;
  document.getElementById("stat-phone").textContent = stats.with_phone ?? 0;
  updateAnalytics(stats);
}

function updateAnalytics(stats) {
  const collected = stats.collected || {};
  const shared = stats.shared || {};
  const colIds = ["today", "week", "month", "year", "all"];
  colIds.forEach((key) => {
    const colEl = document.getElementById(`col-${key}`);
    const shrEl = document.getElementById(`shr-${key}`);
    if (colEl) colEl.textContent = String(collected[key] ?? 0);
    if (shrEl) shrEl.textContent = String(shared[key] ?? 0);
  });
}

function bumpSharedAnalytics() {
  ["today", "week", "month", "year", "all"].forEach((key) => {
    const el = document.getElementById(`shr-${key}`);
    if (el) el.textContent = String((parseInt(el.textContent, 10) || 0) + 1);
  });
}

function updateBulkBar() {
  const n = selectedIds.size;
  bulkBar.classList.toggle("hidden", n === 0);
  bulkCountEl.textContent = n === 1 ? "1 محدّد" : `${n} محدّد`;
}

function updateSelectAllCheckbox(places) {
  if (!selectAllPageCb) return;
  const pageIds = places.map((p) => p.id);
  const selectedOnPage = pageIds.filter((id) => selectedIds.has(id)).length;
  selectAllPageCb.checked = pageIds.length > 0 && selectedOnPage === pageIds.length;
  selectAllPageCb.indeterminate = selectedOnPage > 0 && selectedOnPage < pageIds.length;
}

function togglePlaceSelection(id, checked) {
  if (checked) selectedIds.add(id);
  else selectedIds.delete(id);
  updateBulkBar();
  updateSelectAllCheckbox(savedPlaces);
}

function clearSelection() {
  selectedIds.clear();
  updateBulkBar();
  updateSelectAllCheckbox(savedPlaces);
  savedTableBody.querySelectorAll(".row-check").forEach((cb) => {
    cb.checked = false;
  });
  if (selectAllPageCb) {
    selectAllPageCb.checked = false;
    selectAllPageCb.indeterminate = false;
  }
}

function toggleSelectAllOnPage(checked) {
  savedPlaces.forEach((p) => {
    if (checked) selectedIds.add(p.id);
    else selectedIds.delete(p.id);
  });
  updateBulkBar();
  renderSavedTable(savedPlaces);
}

function updatePaginationUI() {
  const { page, total, total_pages } = pagination;
  pageInfoEl.textContent = formatPagination(page, total_pages, total);
  pagePrevBtn.disabled = page <= 1;
  pageNextBtn.disabled = page >= total_pages;
}

function renderSavedTable(places, highlightId = null) {
  savedTableBody.innerHTML = "";
  if (!places.length) {
    savedTableBody.innerHTML = `<tr><td colspan="8" class="empty-row">لا توجد نتائج في هذه الصفحة.</td></tr>`;
    updateSelectAllCheckbox([]);
    return;
  }

  places.forEach((p) => {
    const tr = document.createElement("tr");
    if (p.whatsapp_shared) tr.classList.add("row-shared");
    if (highlightId === p.id) tr.classList.add("row-just-shared");
    if (selectedIds.has(p.id)) tr.classList.add("row-selected");

    const statusBadge = p.whatsapp_shared
      ? `<span class="tag tag-shared">${icon("clipboard-check")} تم المشاركة</span>`
      : `<span class="tag tag-pending">في الانتظار</span>`;

    const waCell = p.whatsapp_phone
      ? `<button type="button" class="wa-btn">${icon("msgs")} واتساب</button>`
      : `<span class="muted">بدون هاتف</span>`;

    const checked = selectedIds.has(p.id) ? "checked" : "";

    tr.innerHTML = `
      <td class="col-check" data-label=""><input type="checkbox" class="row-check" data-id="${p.id}" aria-label="تحديد ${escapeHtml(p.name || "")}" ${checked} /></td>
      <td class="cell-status" data-label="الحالة">${statusBadge}</td>
      <td class="cell-name" data-label="الاسم">${escapeHtml(p.name || "—")}</td>
      <td class="cell-phone cell-truncate" data-label="الهاتف" dir="ltr">${escapeHtml(p.phone || "—")}</td>
      <td class="cell-email cell-truncate" data-label="البريد" dir="ltr">${escapeHtml(p.email || "—")}</td>
      <td class="cell-city" data-label="المدينة">${escapeHtml(cityLabel(p.city))}</td>
      <td class="cell-wa" data-label="واتساب">${waCell}</td>
      <td class="cell-actions" data-label="إجراءات">
        <div class="row-actions">
          <button type="button" class="icon-btn icon-btn-edit" title="تعديل" aria-label="تعديل">${icon("pen")}</button>
          <button type="button" class="icon-btn icon-btn-delete" title="حذف" aria-label="حذف">${icon("trash")}</button>
        </div>
      </td>
    `;

    const rowCb = tr.querySelector(".row-check");
    rowCb.addEventListener("change", () => {
      togglePlaceSelection(p.id, rowCb.checked);
      tr.classList.toggle("row-selected", rowCb.checked);
    });

    const waBtn = tr.querySelector(".wa-btn");
    if (waBtn) waBtn.addEventListener("click", () => openWhatsApp(p));

    tr.querySelector(".icon-btn-edit").addEventListener("click", () => openEditModal(p));
    tr.querySelector(".icon-btn-delete").addEventListener("click", () => deletePlace(p));

    savedTableBody.appendChild(tr);
  });

  updateSelectAllCheckbox(places);
}

function openEditModal(place) {
  document.getElementById("edit-id").value = place.id;
  document.getElementById("edit-name").value = place.name || "";
  document.getElementById("edit-phone").value = place.phone || "";
  document.getElementById("edit-email").value = place.email || "";
  document.getElementById("edit-address").value = place.address || "";
  document.getElementById("edit-city").value = place.city || "";
  document.getElementById("edit-shared").checked = Boolean(place.whatsapp_shared);
  document.getElementById("edit-modal").classList.remove("hidden");
  initIcons(document.getElementById("edit-modal"));
  document.getElementById("edit-name").focus();
}

function closeEditModal() {
  document.getElementById("edit-modal").classList.add("hidden");
}

async function saveEditPlace(e) {
  e.preventDefault();
  const id = document.getElementById("edit-id").value;
  const payload = {
    name: document.getElementById("edit-name").value.trim(),
    phone: document.getElementById("edit-phone").value.trim() || null,
    email: document.getElementById("edit-email").value.trim() || null,
    address: document.getElementById("edit-address").value.trim() || null,
    city: document.getElementById("edit-city").value || null,
    whatsapp_shared: document.getElementById("edit-shared").checked,
  };
  if (!payload.name) {
    showToast("الاسم مطلوب");
    return;
  }

  const res = await fetch(`/api/places/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(data.detail || "تعذّر الحفظ");
    return;
  }

  closeEditModal();
  showToast("تم حفظ التعديلات ✓");
  if (data.stats) {
    updateStatCards(data.stats);
    dbCountBadge.textContent = String(data.stats.total ?? 0);
    resultsStatsLine.textContent = formatStatsLine(data.stats);
  }
  await loadSavedPlaces({ silent: true });
}

async function deletePlace(place) {
  const name = place.name || "هذا المكان";
  if (!confirm(`حذف «${name}»؟ لا يمكن التراجع.`)) return;

  const res = await fetch(`/api/places/${place.id}`, { method: "DELETE" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(data.detail || "تعذّر الحذف");
    return;
  }

  selectedIds.delete(place.id);
  updateBulkBar();
  showToast("تم الحذف ✓");
  if (data.stats) {
    updateStatCards(data.stats);
    dbCountBadge.textContent = String(data.stats.total ?? 0);
    resultsStatsLine.textContent = formatStatsLine(data.stats);
  }
  await loadSavedPlaces({ silent: true });
}

async function bulkDeletePlaces() {
  const ids = [...selectedIds];
  if (!ids.length) return;
  if (!confirm(`حذف ${ids.length} مكان؟ لا يمكن التراجع.`)) return;

  const res = await fetch("/api/places/bulk-delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(data.detail || "تعذّر الحذف");
    return;
  }

  selectedIds.clear();
  updateBulkBar();
  showToast(`تم حذف ${data.deleted ?? ids.length} ✓`);
  if (data.stats) {
    updateStatCards(data.stats);
    dbCountBadge.textContent = String(data.stats.total ?? 0);
    resultsStatsLine.textContent = formatStatsLine(data.stats);
  }
  await loadSavedPlaces({ silent: true });
}

async function loadSavedPlaces({ silent = false } = {}) {
  if (loadInFlight) return;
  loadInFlight = true;
  try {
    const params = buildQueryParams(false);
    const res = await fetch(`/api/places?${params}`);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    savedPlaces = (data.places || []).map((p) => {
      if (sharingIds.has(p.id)) {
        return { ...p, whatsapp_shared: true, whatsapp_shared_at: p.whatsapp_shared_at || new Date().toISOString() };
      }
      return p;
    });
    pagination = data.pagination || pagination;
    currentPage = pagination.page;
    const stats = data.stats || {};

    dbCountBadge.textContent = String(stats.total ?? 0);
    resultsStatsLine.textContent = formatStatsLine(stats);

    updateStatCards(stats);
    updatePaginationUI();
    renderSavedTable(savedPlaces);
    updateBulkBar();
  } catch (err) {
    if (!silent) showLoadError(err);
  } finally {
    loadInFlight = false;
  }
}

async function fetchAllForExport() {
  const res = await fetch(`/api/places?${buildQueryParams(true)}`);
  const data = await res.json();
  return data.places || [];
}

pagePrevBtn.addEventListener("click", () => {
  if (currentPage > 1) {
    currentPage -= 1;
    loadSavedPlaces();
  }
});

pageNextBtn.addEventListener("click", () => {
  if (currentPage < pagination.total_pages) {
    currentPage += 1;
    loadSavedPlaces();
  }
});

document.getElementById("refresh-results").addEventListener("click", () => loadSavedPlaces());

selectAllPageCb?.addEventListener("change", () => {
  toggleSelectAllOnPage(selectAllPageCb.checked);
});

document.getElementById("bulk-delete")?.addEventListener("click", bulkDeletePlaces);
document.getElementById("bulk-clear")?.addEventListener("click", clearSelection);

document.getElementById("cleanup-invalid").addEventListener("click", async () => {
  if (!confirm("حذف غير المتعلق بالحيوانات + الخاطئ + بدون هاتف؟")) return;
  const res = await fetch("/api/places/cleanup-invalid", { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(data.detail || "تعذّر التنظيف");
    return;
  }
  showToast(`تم — غير حيوانات ${data.deleted_non_pet ?? 0} · حذف ${data.deleted ?? 0} · بدون هاتف ${data.deleted_no_phone ?? 0}`);
  clearSelection();
  if (data.stats) {
    updateStatCards(data.stats);
    dbCountBadge.textContent = String(data.stats.total ?? 0);
    resultsStatsLine.textContent = formatStatsLine(data.stats);
  }
  await loadSavedPlaces();
});

document.getElementById("filter-status").addEventListener("change", () => {
  currentPage = 1;
  clearSelection();
  loadSavedPlaces();
});
document.getElementById("filter-city").addEventListener("change", () => {
  currentPage = 1;
  clearSelection();
  loadSavedPlaces();
});
document.getElementById("filter-search").addEventListener("input", () => {
  clearTimeout(window._searchTimer);
  window._searchTimer = setTimeout(() => {
    currentPage = 1;
    clearSelection();
    loadSavedPlaces();
  }, 300);
});

downloadCsvBtn.addEventListener("click", async () => {
  const rows = await fetchAllForExport();
  downloadFile(`waleef-places-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(rows), "text/csv;charset=utf-8");
});

downloadJsonBtn.addEventListener("click", async () => {
  const rows = await fetchAllForExport();
  downloadFile(`waleef-places-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(rows, null, 2), "application/json");
});

fetch("/api/cities")
  .then((r) => r.json())
  .then((data) => {
    const select = document.getElementById("city");
    const hint = document.getElementById("city-zones-hint");
    const updateHint = () => {
      const c = data.cities.find((x) => x.name === select.value);
      if (c) hint.textContent = `~${c.estimated_zones} منطقة · تقريب تلقائي + إزالة التكرار + حفظ`;
    };
    select.addEventListener("change", updateHint);
    updateHint();
  })
  .catch(() => {});

document.getElementById("edit-form").addEventListener("submit", saveEditPlace);
document.querySelectorAll("[data-close-modal]").forEach((el) => {
  el.addEventListener("click", closeEditModal);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeEditModal();
});

loadSavedPlaces();
tryReconnectActiveJob();
