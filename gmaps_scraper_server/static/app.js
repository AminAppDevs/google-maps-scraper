import { initIcons, icon } from "./icons.js";

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
let loadInFlight = false;

await initIcons();

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
    if (isResultsVisible() && sharingIds.size === 0) loadSavedPlaces({ silent: true });
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

  setStatus("جاري الجمع… سيتم الحفظ في قاعدة البيانات عند الانتهاء.", "loading");

  const res = await fetch("/api/scrape", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query, max_places: maxPlaces, lang,
      headless: true, concurrency: 5, dedupe: true, save_to_db: true,
    }),
  });

  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.detail || "فشل الطلب");

  const n = data.results?.length ?? 0;
  const saved = data.save_stats;
  let msg = `تم — ${n} مكان تم جمعه.`;
  if (saved) msg += ` قاعدة البيانات: ${saved.inserted} جديد، ${saved.updated} محدّث.`;
  setStatus(msg, "success");
  currentPage = 1;
  switchToResultsTab();
}

async function scrapeCityStream() {
  const city = document.getElementById("city").value;
  const keyword = document.getElementById("city-keyword").value.trim() || null;
  const lang = document.getElementById("city-lang").value;
  const zoom = parseInt(document.getElementById("zoom").value, 10) || 15;
  const cellSize = parseFloat(document.getElementById("cell-size").value) || 4;
  const includeVet = document.getElementById("include-vet").checked;

  setStatus(`جاري مسح ${cityLabel(city)}… النتائج تُحفظ تلقائياً.`, "loading");
  setProgress(0, 1, "جاري البدء…");

  const res = await fetch("/api/scrape-city/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      city, keyword, lang, zoom, cell_size_km: cellSize,
      max_per_cell: 120, headless: true, concurrency: 5,
      include_vet_clinics: includeVet, save_to_db: true,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "فشل مسح المدينة");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);

      if (event.type === "start") setProgress(0, event.total_steps, event.message);
      else if (event.type === "progress") {
        setProgress(event.step, event.total_steps, event.message);
        if (isResultsVisible()) loadSavedPlaces({ silent: true });
      } else if (event.type === "error") throw new Error(event.message);
      else if (event.type === "complete") {
        hideProgress();
        let msg = event.message;
        if (event.save_stats) {
          msg += ` · قاعدة البيانات: ${event.save_stats.inserted} جديد، ${event.save_stats.updated} محدّث`;
        }
        setStatus(msg, "success");
        currentPage = 1;
        switchToResultsTab();
        return;
      }
    }
  }
  throw new Error("انتهى مسح المدينة بشكل غير متوقع");
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  submitBtn.disabled = true;
  hideProgress();
  try {
    if (currentMode === "city") await scrapeCityStream();
    else await scrapeSingle();
  } catch (err) {
    hideProgress();
    setStatus(err.message || "حدث خطأ ما.", "error");
  } finally {
    submitBtn.disabled = false;
  }
});

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
  const url = buildWhatsAppDesktopUrl(place);
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

function updatePaginationUI() {
  const { page, total, total_pages } = pagination;
  pageInfoEl.textContent = formatPagination(page, total_pages, total);
  pagePrevBtn.disabled = page <= 1;
  pageNextBtn.disabled = page >= total_pages;
}

function renderSavedTable(places, highlightId = null) {
  savedTableBody.innerHTML = "";
  if (!places.length) {
    savedTableBody.innerHTML = `<tr><td colspan="7" class="empty-row">لا توجد نتائج في هذه الصفحة.</td></tr>`;
    return;
  }

  places.forEach((p) => {
    const tr = document.createElement("tr");
    if (p.whatsapp_shared) tr.classList.add("row-shared");
    if (highlightId === p.id) tr.classList.add("row-just-shared");

    const statusBadge = p.whatsapp_shared
      ? `<span class="tag tag-shared">${icon("clipboard-check")} تم المشاركة</span>`
      : `<span class="tag tag-pending">في الانتظار</span>`;

    const waCell = p.whatsapp_phone
      ? `<button type="button" class="wa-btn">${icon("msgs")} واتساب</button>`
      : `<span class="muted">بدون هاتف</span>`;

    tr.innerHTML = `
      <td>${statusBadge}</td>
      <td>${escapeHtml(p.name || "—")}</td>
      <td dir="ltr">${escapeHtml(p.phone || "—")}</td>
      <td dir="ltr">${escapeHtml(p.email || "—")}</td>
      <td>${escapeHtml(cityLabel(p.city))}</td>
      <td>${waCell}</td>
      <td>
        <div class="row-actions">
          <button type="button" class="icon-btn icon-btn-edit" title="تعديل" aria-label="تعديل">${icon("pen")}</button>
          <button type="button" class="icon-btn icon-btn-delete" title="حذف" aria-label="حذف">${icon("trash")}</button>
        </div>
      </td>
    `;

    const waBtn = tr.querySelector(".wa-btn");
    if (waBtn) waBtn.addEventListener("click", () => openWhatsApp(p));

    tr.querySelector(".icon-btn-edit").addEventListener("click", () => openEditModal(p));
    tr.querySelector(".icon-btn-delete").addEventListener("click", () => deletePlace(p));

    savedTableBody.appendChild(tr);
  });
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

  showToast("تم الحذف ✓");
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
    const data = await res.json();
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

document.getElementById("cleanup-invalid").addEventListener("click", async () => {
  if (!confirm("حذف المتاجر الخاطئة وكل مكان بدون رقم هاتف سعودي؟")) return;
  const res = await fetch("/api/places/cleanup-invalid", { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(data.detail || "تعذّر التنظيف");
    return;
  }
  showToast(`تم — حذف ${data.deleted ?? 0} · بدون هاتف ${data.deleted_no_phone ?? 0} · إصلاح ${data.fixed ?? 0}`);
  if (data.stats) {
    updateStatCards(data.stats);
    dbCountBadge.textContent = String(data.stats.total ?? 0);
    resultsStatsLine.textContent = formatStatsLine(data.stats);
  }
  await loadSavedPlaces();
});

document.getElementById("filter-status").addEventListener("change", () => {
  currentPage = 1;
  loadSavedPlaces();
});
document.getElementById("filter-city").addEventListener("change", () => {
  currentPage = 1;
  loadSavedPlaces();
});
document.getElementById("filter-search").addEventListener("input", () => {
  clearTimeout(window._searchTimer);
  window._searchTimer = setTimeout(() => {
    currentPage = 1;
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
