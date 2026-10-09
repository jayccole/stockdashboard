import { lineChart } from "./chart.js";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v, d = 2) => v == null ? "—" : v.toLocaleString(undefined, { style: "currency", currency: "USD", minimumFractionDigits: d, maximumFractionDigits: d });
const price = (v) => v == null ? "—" : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: v < 10 ? 4 : 2 });
const pct = (v) => v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}%`;
const compact = (v) => v == null ? "—" : Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(v);
const when = (t) => t ? new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
const chg = (v, text = pct(v)) => `<span class="chg ${v > 0 ? "up" : v < 0 ? "down" : ""}">${text}</span>`;

function getToken() { try { return localStorage.getItem("dashToken") || ""; } catch { return ""; } }
function setToken(t) { try { localStorage.setItem("dashToken", t); } catch { /* storage blocked */ } }

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, { ...opts, headers: { "X-Dashboard-Token": getToken(), ...(opts.headers || {}) } });
  if (res.status === 401) { await login(); return api(path, opts); }
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function login() {
  return new Promise((resolve) => {
    const dlg = $("#login");
    dlg.addEventListener("close", () => { setToken($("#token").value.trim()); resolve(); }, { once: true });
    dlg.showModal();
  });
}

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 3000);
}

// ---------- tabs ----------
const loaders = { watchlist: loadWatchlist, trades: loadOrders, advisor: loadAdviceFull, jobs: loadJobs };
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
  document.querySelectorAll(".tab-panel").forEach((p) => { p.hidden = p.id !== `tab-${b.dataset.tab}`; });
  loaders[b.dataset.tab]().catch(fail);
}));
const fail = (e) => toast(e.message.slice(0, 160));

// ---------- sortable table ----------
function table(el, cols, rows, { onClick, sortKey, sortDir = -1, empty = "Nothing here yet." } = {}) {
  let key = sortKey, dir = sortDir;
  const render = () => {
    const sorted = key ? [...rows].sort((a, b) => {
      const va = cols.find((c) => c.key === key).sort?.(a) ?? a[key], vb = cols.find((c) => c.key === key).sort?.(b) ?? b[key];
      if (va == null) return 1; if (vb == null) return -1;
      return (va > vb ? 1 : va < vb ? -1 : 0) * dir;
    }) : rows;
    el.innerHTML = `<thead><tr>${cols.map((c) => `<th class="${c.num ? "num" : ""}" data-key="${c.key}" aria-sort="${c.key === key ? (dir > 0 ? "ascending" : "descending") : "none"}">${c.label}</th>`).join("")}</tr></thead>
      <tbody>${sorted.length ? sorted.map((r, i) => `<tr data-i="${rows.indexOf(r)}" class="${onClick ? "clickable" : ""}" ${onClick ? 'tabindex="0"' : ""}>${cols.map((c) => `<td class="${c.num ? "num" : ""} ${c.cls || ""}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join("")}</tr>`).join("")
        : `<tr><td colspan="${cols.length}" class="empty">${empty}</td></tr>`}</tbody>`;
    el.querySelectorAll("th").forEach((th) => th.addEventListener("click", () => {
      dir = th.dataset.key === key ? -dir : -1; key = th.dataset.key; render();
    }));
    if (onClick) el.querySelectorAll("tbody tr[data-i]").forEach((tr) => {
      const go = () => { el.querySelectorAll("tr").forEach((x) => x.removeAttribute("aria-selected")); tr.setAttribute("aria-selected", "true"); onClick(rows[+tr.dataset.i]); };
      tr.addEventListener("click", go);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    });
  };
  render();
}

// ---------- watchlist ----------
function rangeCell(q) {
  if (q.week52_low == null || q.week52_high == null || q.price == null) return "—";
  const f = Math.min(1, Math.max(0, (q.price - q.week52_low) / (q.week52_high - q.week52_low || 1)));
  return `<div class="range" title="52-week range: ${price(q.week52_low)} to ${price(q.week52_high)}">
    <span>${price(q.week52_low)}</span><span class="track"><span class="dot" style="left:${(f * 100).toFixed(1)}%"></span></span><span>${price(q.week52_high)}</span></div>`;
}

async function loadWatchlist() {
  const [lists, acct, advice] = await Promise.all([api("/watchlists"), api("/account"), api("/advice/latest")]);
  const sel = $("#wl-filter");
  if (!sel.options.length) {
    sel.innerHTML = `<option value="">All watchlists</option>` + lists.map((l) => `<option value="${esc(l.id)}">${esc(l.name)} (${l.count})</option>`).join("");
    sel.addEventListener("change", () => loadQuotes().catch(fail));
  }
  renderAccount(acct);
  renderAdviceBrief(advice);
  await loadQuotes();
}

async function loadQuotes() {
  const id = $("#wl-filter").value;
  const quotes = await api(`/quotes${id ? `?watchlist_id=${encodeURIComponent(id)}` : ""}`);
  const latest = quotes.reduce((m, q) => (q.captured_at > m ? q.captured_at : m), "");
  $("#as-of").textContent = latest ? `Prices as of ${when(latest)}` : "No quotes pulled yet";
  table($("#quotes"), [
    { key: "symbol", label: "Symbol", cls: "sym", sort: (r) => r.symbol },
    { key: "name", label: "Name", cls: "name" },
    { key: "price", label: "Last", num: true, render: (r) => price(r.ext_price ?? r.price) },
    { key: "change_pct", label: "Day", num: true, render: (r) => chg(r.change_pct) },
    { key: "volume", label: "Volume", num: true, render: (r) => compact(r.volume) },
    { key: "range", label: "52-week range", sort: (r) => (r.price - r.week52_low) / ((r.week52_high - r.week52_low) || 1), render: rangeCell },
    { key: "pe_ratio", label: "P/E", num: true, render: (r) => r.pe_ratio == null || r.pe_ratio <= 0 ? "—" : r.pe_ratio.toFixed(1) },
  ], quotes, { onClick: showDetail, sortKey: "symbol", sortDir: 1,
    empty: 'No quotes yet. Open Data jobs and run "Run full nightly refresh" to pull your watchlists.' });
}

function renderAccount({ latest }) {
  const el = $("#account");
  if (!latest) { el.innerHTML = `<h2>Account</h2><p class="empty">No account snapshot yet.</p>`; return; }
  el.innerHTML = `<h2>Account</h2>
    <div class="big">${money(latest.net_liquidation)}</div>
    <dl class="kv">
      <dt>Cash</dt><dd>${money(latest.cash)}</dd>
      <dt>Buying power</dt><dd>${money(latest.buying_power)}</dd>
      <dt>Market value</dt><dd>${money(latest.market_value)}</dd>
      <dt>Today</dt><dd>${chg(latest.day_pl, money(latest.day_pl))}</dd>
      <dt>Unrealized</dt><dd>${chg(latest.unrealized_pl, money(latest.unrealized_pl))}</dd>
      <dt>Positions</dt><dd>${latest.positions.length}</dd>
    </dl>
    <p class="muted">Updated ${when(latest.captured_at)}</p>
    ${latest.positions.length ? `<h3 style="margin-top:12px">Positions</h3><ul class="plain">${latest.positions.map((p) =>
      `<li><b>${esc(p.symbol)}</b> ${p.quantity ?? ""} @ ${price(p.cost_price)} ${chg(p.unrealized_pl, money(p.unrealized_pl))}</li>`).join("")}</ul>` : ""}`;
}

const STANCE = { watch_for_entry: "Watch for entry", momentum: "Momentum", extended: "Extended", weak: "Weak", no_signal: "No clear signal" };

function renderAdviceBrief(a) {
  const el = $("#advice-brief");
  if (!a) { el.innerHTML = `<h2>Advisor</h2><p class="empty">No review yet. It runs after the nightly refresh, or start one from the Advisor tab.</p>`; return; }
  const top = a.ideas.filter((i) => i.stance !== "no_signal").slice(0, 4);
  el.innerHTML = `<h2>Advisor</h2><p class="muted">${when(a.created_at)}</p>
    <ul class="plain">${top.map((i) => `<li><b>${esc(i.symbol)}</b> <span class="tag">${STANCE[i.stance] || esc(i.stance)}</span>${esc(i.rationale).slice(0, 140)}${i.rationale.length > 140 ? "…" : ""}</li>`).join("")}</ul>`;
}

async function showDetail(q) {
  const el = $("#detail");
  el.hidden = false;
  el.innerHTML = `<div class="panel-head"><h2>${esc(q.symbol)} <span class="muted">${esc(q.name || "")}</span></h2>
    <div class="range-btns">${[["1M", 31], ["3M", 92], ["6M", 183], ["1Y", 366]].map(([l, d]) => `<button class="btn" data-days="${d}" aria-pressed="${d === 183}">${l}</button>`).join("")}</div></div>
    <div class="chart" id="price-chart"></div>`;
  const draw = async (days) => {
    const bars = await api(`/symbols/${encodeURIComponent(q.symbol)}/bars?days=${days}`);
    lineChart($("#price-chart"), bars.map((b) => ({ x: new Date(b.day + "T00:00:00"), y: b.close })),
      { fmt: (v) => price(v), label: `${q.symbol} daily close` });
  };
  el.querySelectorAll("[data-days]").forEach((b) => b.addEventListener("click", () => {
    el.querySelectorAll("[data-days]").forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(+b.dataset.days).catch(fail);
  }));
  await draw(183);
  el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
}

// ---------- trades ----------
async function loadOrders() {
  const orders = await api("/orders");
  table($("#orders"), [
    { key: "placed_at", label: "Placed", render: (r) => when(r.placed_at) },
    { key: "symbol", label: "Symbol", cls: "sym" },
    { key: "side", label: "Side" },
    { key: "type", label: "Type" },
    { key: "status", label: "Status" },
    { key: "quantity", label: "Qty", num: true },
    { key: "filled_quantity", label: "Filled", num: true },
    { key: "filled_price", label: "Fill price", num: true, render: (r) => price(r.filled_price) },
  ], orders, { sortKey: "placed_at", empty: "No orders stored yet. Pull order history to load your trades." });
}

// ---------- advisor ----------
async function loadAdviceFull() {
  const [a, health] = await Promise.all([api("/advice/latest"), api("/health")]);
  const el = $("#advice-full");
  const runBtn = health.advisor_enabled ? `<button class="btn primary" data-run="advisor">Run a new review</button>`
    : `<span class="muted">Set ANTHROPIC_API_KEY on the server to enable reviews.</span>`;
  if (!a) { el.innerHTML = `<div class="panel-head"><h2>Advisor</h2>${runBtn}</div><p class="empty">No review yet.</p>`; bindRun(el); return; }
  el.innerHTML = `<div class="panel-head"><h2>Advisor review</h2><span class="muted">${when(a.created_at)} by ${esc(a.model)}</span>${runBtn}</div>
    <div class="prose">${esc(a.summary).split(/\n{2,}/).map((p) => `<p>${p}</p>`).join("")}</div>
    <h3 style="margin-top:16px">Watchlist ideas</h3>
    ${a.ideas.map((i) => `<div class="idea"><div class="sym">${esc(i.symbol)}</div><div>
      <span class="tag">${STANCE[i.stance] || esc(i.stance)}</span><span class="tag">${esc(i.confidence)} confidence</span>${i.likely_you_trade ? '<span class="tag">Fits how you trade</span>' : ""}
      <p style="margin:6px 0 0">${esc(i.rationale)}</p></div></div>`).join("")}
    <h3 style="margin-top:16px">Your trading habits</h3><ul class="plain">${a.habits.map((h) => `<li>${esc(h)}</li>`).join("") || "<li>Not enough trade history yet.</li>"}</ul>
    <h3 style="margin-top:16px">Risks</h3><ul class="plain">${a.risks.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>
    <p class="disclaimer">Generated from your stored data for decision support. Not financial advice.</p>`;
  bindRun(el);
}

// ---------- jobs ----------
async function loadJobs() {
  const jobs = await api("/jobs");
  table($("#jobs"), [
    { key: "started_at", label: "Started", render: (r) => when(r.started_at) },
    { key: "job", label: "Job" },
    { key: "status", label: "Result", render: (r) => `<span class="status-${r.status === "error" ? "error" : "ok"}">${esc(r.status)}</span>` },
    { key: "detail", label: "Detail (click a row for full text)", render: (r) => `<span title="${esc(r.detail)}">${esc((r.detail || "").split("\n")[0]).slice(0, 90)}</span>` },
  ], jobs, { sortKey: "started_at", empty: "No jobs have run yet.",
    onClick: (r) => { const pre = $("#job-detail"); pre.hidden = false; pre.textContent = `${r.job} · ${r.status} · ${when(r.started_at)}\n\n${r.detail || "(no detail)"}`; } });
}

function bindRun(root) {
  root.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try { await api(`/jobs/${b.dataset.run}/run`, { method: "POST" }); toast(`Started ${b.textContent.toLowerCase()}. Results appear on the Data jobs tab.`); }
    catch (e) { fail(e); } finally { setTimeout(() => { b.disabled = false; }, 4000); }
  }));
}
bindRun(document);
$("#refresh").addEventListener("click", async () => {
  try { await api("/jobs/pull_quotes/run", { method: "POST" }); toast("Pulling quotes…"); setTimeout(() => loadQuotes().catch(fail), 6000); }
  catch (e) { fail(e); }
});

loadWatchlist().catch(fail);
setInterval(() => { if (!$("#tab-watchlist").hidden && !document.hidden) loadQuotes().catch(() => {}); }, 60_000);
