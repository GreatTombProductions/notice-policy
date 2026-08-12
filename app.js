/* Notice-Policy Check — render compliance.json */
const DATA_BASE = "data/";

let DATA = null;

const fmt = d => d ? d : "—";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const badge = v => v === "PASS" ? `<span class="vbadge pass">PASS</span>`
              : v === "SHORT" ? `<span class="vbadge short">SHORT</span>`
              : `<span class="vbadge na">n/a</span>`;

function ordinal(n) {
  const s = ["th","st","nd","rd"], v = n % 100;
  return n + (s[(v-20)%10] || s[v] || s[0]);
}

function floorLabel(fl) {
  const unit = fl.unit === "months" ? (fl.min === 1 ? "month" : "months")
             : fl.unit === "weeks" ? (fl.min === 1 ? "week" : "weeks")
             : fl.min === 1 ? "day" : "days";
  return `${fl.min} ${unit}`;
}

function renderSummary() {
  const el = document.getElementById("summary");
  const html = Object.entries(DATA.track_records).map(([vendor, tr]) => {
    const pol = DATA.policies[vendor];
    const floors = (pol.floors || []).map(f => `<span class="floor">${esc(f.quote)}</span>`).join("");
    const below = Object.entries(tr.below_floor || {}).map(([k, n]) => `<span class="floor">${n} below ${esc(k)} floor</span>`).join("");
    const verdict = tr.with_notice > 0 && tr.min_days !== null
      ? (Object.values(tr.below_floor || {}).some(n => n > 0)
          ? `<span class="vbadge short">SHORTFALLS ON RECORD</span>`
          : `<span class="vbadge pass">FLOOR HONORED</span>`)
      : `<span class="vbadge na">no computable notice</span>`;
    return `<div class="card">
      <h3>${esc(vendor)} ${verdict}</h3>
      ${floors}
      <div class="stat"><span>Retirements with computable notice</span><b>${tr.with_notice}</b></div>
      <div class="stat"><span>Notice range</span><b>${tr.min_days !== null ? `${tr.min_days}–${tr.max_days} days` : "—"}</b></div>
      <div class="stat"><span>Median notice</span><b>${tr.median_days !== null ? `${tr.median_days} days` : "—"}</b></div>
      ${below ? `<div class="stat"><span>Below stated floors</span><b>${below}</b></div>` : ""}
      <div class="verdict-line">${tr.by_status ? `${tr.by_status.retired ?? 0} completed retirements · ${tr.by_status.deprecated ?? 0} scheduled` : ""}</div>
    </div>`;
  }).join("");
  el.innerHTML = html;
}

function renderPolicies() {
  const el = document.getElementById("policies");
  const html = Object.entries(DATA.policies).map(([vendor, pol]) => {
    if (pol.note && !(pol.floors || []).length) {
      return `<div class="vendor-policy"><h3>${esc(vendor)}</h3><p class="gap">${esc(pol.note)}</p></div>`;
    }
    const floors = (pol.floors || []).map(f => `<span class="floor">${esc(f.quote)}</span>`).join("");
    const escape = pol.escape_hatch ? `<p class="escape">Escape clause: “${esc(pol.escape_hatch)}”</p>` : "";
    return `<div class="vendor-policy">
      <h3>${esc(vendor)} <a href="${esc(pol.source_url)}" target="_blank" rel="noopener">source ↗</a></h3>
      <p class="quote">“${esc(pol.text)}”</p>
      ${floors}
      ${escape}
    </div>`;
  }).join("");
  el.innerHTML = html;
}

function modelRows(vendor) {
  return DATA.models.filter(m => m.vendor === vendor && m.status !== "active");
}

function renderVendorTable(vendor, group) {
  const models = modelRows(vendor).filter(m => m.status === group);
  if (!models.length) return "";
  const isOpenAI = vendor === "OpenAI";
  const order = group === "deprecated"
    ? [...models].sort((a, b) => (a.retirement || "").localeCompare(b.retirement || ""))
    : [...models].sort((a, b) => (b.retirement || "").localeCompare(a.retirement || ""));
  const head = isOpenAI
    ? `<th>Model</th><th class="num">Announced</th><th class="num">Retirement</th><th class="num">Days</th><th class="num">vs GA (6&nbsp;mo)</th><th class="num">vs Spec (3&nbsp;mo)</th><th class="num">vs Preview (2&nbsp;wk)</th>`
    : `<th>Model</th><th class="num">Announced</th><th class="num">Retirement</th><th class="num">Days</th><th class="num">vs 60-day floor</th>`;
  const rows = order.map(m => {
    const previewTag = m.is_preview ? `<span class="preview-tag">preview</span>` : "";
    const name = `<span title="${esc(m.model_id)}">${esc(m.family)}</span>${previewTag}`;
    const statusTag = `<span class="status-tag ${m.status}">${m.status}</span>`;
    const days = m.notice_days !== null ? m.notice_days : "—";
    if (isOpenAI) {
      const v = m.verdicts || {};
      const vCell = cls => v[cls] ? `${badge(v[cls].verdict)}<span class="floor-sub">${v[cls].floor_days}d floor</span>` : badge(null);
      return `<tr><td>${name} ${statusTag}</td><td class="num">${fmt(m.announced)}</td><td class="num">${fmt(m.retirement)}</td><td class="num"><b>${days}</b></td><td>${vCell("ga")}</td><td>${vCell("specialized")}</td><td>${vCell("preview")}</td></tr>`;
    }
    const v = (m.verdicts && m.verdicts["publicly released models"]) || null;
    const vCell = v ? `${badge(v.verdict)}<span class="floor-sub">${v.floor_days}d floor</span>` : badge(null);
    return `<tr><td>${name} ${statusTag}</td><td class="num">${fmt(m.announced)}</td><td class="num">${fmt(m.retirement)}</td><td class="num"><b>${days}</b></td><td>${vCell}</td></tr>`;
  });
  const title = group === "deprecated" ? `⚠ ${vendor} — scheduled retirements (deprecated, shutdown pending)` : `☠ ${vendor} — completed retirements`;
  return `<table><caption>${title} <span style="color:var(--muted);font-weight:400">(${order.length})</span></caption>
    <thead><tr>${head}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

function renderTables(filterText, hidePass) {
  const el = document.getElementById("tables");
  const q = (filterText || "").toLowerCase();
  const prevHide = hidePass;
  // Apply client-side filtering by setting display via dataset on rows; simplest:
  // rebuild with a class we can toggle. We re-render here with filtering done in CSS-free way:
  el.innerHTML = "";
  ["Anthropic", "OpenAI"].forEach(vendor => {
    const tables = [renderVendorTable(vendor, "deprecated"), renderVendorTable(vendor, "retired")];
    const wrap = document.createElement("div");
    wrap.innerHTML = tables.join("");
    if (q) {
      wrap.querySelectorAll("tbody tr").forEach(tr => {
        if (!tr.textContent.toLowerCase().includes(q)) tr.classList.add("hidden");
      });
    }
    if (prevHide) {
      wrap.querySelectorAll("tbody tr").forEach(tr => {
        const cells = tr.querySelectorAll("td");
        const passOnly = [...cells].every(cd => !cd.querySelector(".vbadge.short"));
        if (passOnly) tr.classList.add("hidden");
      });
    }
    el.appendChild(wrap);
  });
}

function renderTracks() {
  const el = document.getElementById("tracks");
  const html = ["Anthropic", "OpenAI"].map(vendor => {
    const completed = DATA.models
      .filter(m => m.vendor === vendor && m.status === "retired" && m.notice_days !== null)
      .sort((a, b) => (a.retirement || "").localeCompare(b.retirement || ""));
    if (!completed.length) return "";
    const maxD = Math.max(...completed.map(m => m.notice_days));
    const rows = completed.map(m => {
      const primaryFloor = m.primary_verdict !== null ? (m.verdicts[m.primary_floor] || {}).floor_days : null;
      const cls = m.primary_verdict === "SHORT" ? "short" : "pass";
      const width = primaryFloor ? Math.min(100, (m.notice_days / primaryFloor) * 100) : Math.min(100, (m.notice_days / maxD) * 100);
      return `<div class="bar-row"><div class="bar-label" title="${esc(m.model_id)}">${esc(m.family)}</div>
        <div class="bar-track"><div class="bar-fill ${cls}" style="width:${width}%"></div></div>
        <div class="bar-days">${m.notice_days}d</div></div>`;
    }).join("");
    return `<div class="track-vendor"><h3>${esc(vendor)} — completed retirements, oldest → newest</h3>${rows}</div>`;
  }).join("");
  el.innerHTML = html;
}

function renderMethod() {
  const el = document.getElementById("method");
  el.innerHTML = `
    <p><b>What is being measured.</b> For every model with an announcement date and a retirement (shutdown) date on the vendor's own page, the notice interval is <code>retirement − announcement</code>, in days. “Announcement” is the date the vendor says it notified developers (each deprecation section on both pages carries a dated header, e.g. <code>2026-06-05: Claude Opus 4.1 model</code>).</p>
    <p><b>The floors are the vendors' own words.</b> OpenAI: “Generally available models: At least 6 months.” Anthropic: “at least 60 days' notice before model retirement for publicly released models.” Month floors are evaluated with calendar-month arithmetic (announcement + 6 months), which is the truest reading of “6 months”; this can differ from a flat-day count by 1–2 days near the boundary.</p>
    <p><b>Which floor applies.</b> For models whose name contains <code>preview</code> (the vendor's own criterion: “identified by preview in the model name”), the preview floor (≈2 weeks) is the primary comparison; all other models are compared against the GA floor (6 months). The other floors are shown on every row so you can apply any class judgment yourself.</p>
    <p><b>What is NOT asserted.</b> This tool does not adjudicate the vendor's escape hatch (“Unless safety or compliance concerns require a faster timeline…”) — it quotes it and reports the record. A SHORT row is the record; whether the exception applies is the vendor's claim to make with evidence.</p>
    <p><b>Honest coverage.</b> A model with no announcement date on the page is listed as <span class="vbadge na">n/a</span> with its reason — never assumed. DeepSeek publishes no deprecation page and is listed as a documented gap, not hidden. API/system deprecations (Assistants API, legacy endpoints) are excluded — the stated notice floors apply to models.</p>
    <p><b>Refresh.</b> Snapshot generated ${DATA.as_of ? "as of " + DATA.as_of : ""}. Re-run <code>pipeline/fetch.py</code> then <code>pipeline/generate.py</code>; vendor pages are the source of truth and change without notice.</p>`;
}

async function init() {
  try {
    const resp = await fetch(DATA_BASE + "compliance.json");
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    DATA = await resp.json();
  } catch (e) {
    document.getElementById("summary").innerHTML =
      `<div class="card"><h3>Data failed to load</h3><p class="gap">${esc(e.message)} — the data file is missing or the site was deployed without it.</p></div>`;
    return;
  }
  const asof = document.getElementById("asof");
  asof.innerHTML = `Snapshot as of ${esc(DATA.as_of)} · generated ${esc((DATA.generated_at || "").replace("T", " ").replace("+00:00", " UTC"))} · sources: ${esc(DATA.sources.map(s => `${s.vendor} (${s.status})`).join(", "))}`;
  renderSummary();
  renderPolicies();
  renderTables("", false);
  renderTracks();
  renderMethod();
  const search = document.getElementById("search");
  const hidePass = document.getElementById("hidePass");
  search.addEventListener("input", () => renderTables(search.value, hidePass.checked));
  hidePass.addEventListener("change", () => renderTables(search.value, hidePass.checked));
}

init();
