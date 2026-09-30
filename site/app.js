// BhashaGap front end. Plain JavaScript, no framework: reads data/summary.json and data/topics.json.

const STATUS = { 0: "missing", 1: "stub", 2: "partial", 3: "good" };
const STATUS_LABEL = { missing: "missing", stub: "stub", partial: "partial", good: "good" };
const METRICS = {
  access: {
    label: "Knowledge Access Score",
    help: "Out of 100. If a reader looked up the topics people actually read, how much of the English content would they find in this language?",
    value: (l) => l.access, max: () => 100, fmt: (v) => v.toFixed(0), sort: -1, showEnglish: true,
  },
  coverage: {
    label: "Topics with any article",
    help: "Share of topics that have an article of any length, even a stub.",
    value: (l) => l.coverage * 100, max: () => 100, fmt: (v) => `${v.toFixed(0)}%`, sort: -1, showEnglish: true,
  },
  speakersPerArticle: {
    label: "Speakers per article",
    help: "How many first-language speakers share each existing article. Higher means a bigger gap. (Approximate Census 2011 speaker numbers.)",
    value: (l) => l.speakersPerArticle || 0, max: (ls) => Math.max(...ls.map((l) => l.speakersPerArticle || 0)),
    fmt: (v) => indianNumber(v), sort: -1, showEnglish: false,
  },
};

let DATA = null;
let TOPICS = [];
const $ = (sel) => document.querySelector(sel);

// ---------- formatting ----------
function indianNumber(n) {
  if (n >= 1e7) return `${(n / 1e7).toFixed(n >= 1e8 ? 0 : 1)} crore`;
  if (n >= 1e5) return `${(n / 1e5).toFixed(n >= 1e6 ? 0 : 1)} lakh`;
  return Math.round(n).toLocaleString("en-IN");
}
const pct = (x) => `${Math.round(x * 100)}%`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const wikiUrl = (code, title) => `https://${code}.wikipedia.org/wiki/${encodeURIComponent(title.replace(/ /g, "_"))}`;
const langBy = (code) => DATA.languages.find((l) => l.code === code);
const catLabel = (key) => (DATA.categories.find((c) => c.key === key) || { label: key }).label;
function monthLabel(yyyymm) {
  if (!yyyymm || yyyymm.length < 6) return "";
  const d = new Date(Number(yyyymm.slice(0, 4)), Number(yyyymm.slice(4, 6)) - 1, 1);
  return d.toLocaleString("en-IN", { month: "short", year: "numeric" });
}

// ---------- tooltip ----------
const tip = $("#tooltip");
function showTip(html, evt) {
  tip.innerHTML = html;
  tip.hidden = false;
  const pad = 14;
  const { innerWidth: w, innerHeight: h } = window;
  const rect = tip.getBoundingClientRect();
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + rect.width > w - 8) x = evt.clientX - rect.width - pad;
  if (y + rect.height > h - 8) y = evt.clientY - rect.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}
const hideTip = () => (tip.hidden = true);

// ---------- intro ----------
function renderIntro() {
  const { meta, languages } = DATA;
  $("#demo-banner").hidden = !meta.demo;
  const avg = languages.reduce((s, l) => s + l.access, 0) / languages.length;
  const best = languages[0];
  const worst = languages[languages.length - 1];
  $("#lede").innerHTML =
    `Across ${languages.length} Indian languages, a Wikipedia reader finds on average <span class="big">${avg.toFixed(0)}%</span>
     of what an English reader finds on the same ${meta.topics} everyday topics, from dengue to crop insurance to the Right to Information.
     In ${esc(best.name)} it is ${best.access.toFixed(0)}%. In ${esc(worst.name)}, ${worst.access.toFixed(0)}%.`;
  const facts = [
    ["Topics checked", meta.topics.toLocaleString("en-IN")],
    ["Languages", meta.languages],
    ["Articles found", meta.articles.toLocaleString("en-IN")],
    ["Missing", pct(meta.missingPairs / meta.pairs)],
  ];
  $("#facts").innerHTML = facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  $("#m-topics").textContent = meta.topics.toLocaleString("en-IN");
  $("#m-period").textContent = meta.period_start ? `${monthLabel(meta.period_start)} to ${monthLabel(meta.period_end)}` : "not collected";
  $("#m-updated").textContent = new Date(meta.run_at + "Z").toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
}

// ---------- section 1: bars ----------
function renderBars(metricKey) {
  const m = METRICS[metricKey];
  document.querySelectorAll(".controls button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.metric === metricKey)));
  $("#metric-help").textContent = m.help;
  const langs = [...DATA.languages].sort((a, b) => m.sort * (m.value(a) - m.value(b)));
  const max = m.max(DATA.languages) || 1;
  const rows = [];
  if (m.showEnglish) {
    rows.push(`<div class="bar-row english" aria-label="English reference: 100">
      <span class="bar-label"><span class="native">English</span><span class="en">for comparison</span></span>
      <span class="bar-track"><span class="bar-fill" style="width:100%"></span></span>
      <span class="bar-value">${metricKey === "coverage" ? "100%" : "100"}</span></div>`);
  }
  for (const l of langs) {
    const v = m.value(l);
    rows.push(`<button class="bar-row" data-code="${l.code}" aria-label="${esc(l.name)}: ${m.fmt(v)}">
      <span class="bar-label"><span class="native" lang="${l.code}">${esc(l.native)}</span><span class="en">${esc(l.name)}</span></span>
      <span class="bar-track"><span class="bar-fill" style="width:${(100 * v) / max}%"></span></span>
      <span class="bar-value">${m.fmt(v)}</span></button>`);
  }
  const el = $("#bars");
  el.innerHTML = rows.join("");
  el.querySelectorAll("button.bar-row").forEach((row) => {
    const l = langBy(row.dataset.code);
    row.addEventListener("mousemove", (e) =>
      showTip(`<b>${esc(l.name)}</b><br>${l.present} of ${l.topics} topics have an article<br>${l.stubs} are stubs · ${pct(l.fresh || 0)} edited in the last year<br><i>Click to see what to write first</i>`, e));
    row.addEventListener("mouseleave", hideTip);
    row.addEventListener("click", () => {
      $("#lang-select").value = l.code;
      renderLanguage(l.code);
      document.getElementById("explore").scrollIntoView();
    });
  });
}

// ---------- section 2: heatmap ----------
function renderHeatmap() {
  const cats = DATA.categories;
  const langs = DATA.languages;
  const cell = new Map(DATA.categoryScores.map((c) => [`${c.lang}|${c.category}`, c]));
  const step = (v) => Math.min(6, Math.floor(v * 7));
  const el = $("#heatmap");
  el.style.gridTemplateColumns = `minmax(150px, auto) repeat(${cats.length}, minmax(84px, 1fr))`;
  const html = [`<div></div>`, ...cats.map((c) => `<div class="heat-head">${esc(c.label)}<br><span style="font-weight:400;color:var(--muted)">${c.count} topics</span></div>`)];
  for (const l of langs) {
    html.push(`<div class="heat-lang"><span class="native" lang="${l.code}">${esc(l.native)}</span><span class="en">${esc(l.name)}</span></div>`);
    for (const c of cats) {
      const s = cell.get(`${l.code}|${c.key}`);
      const v = s ? s.coverage : 0;
      const k = step(v);
      html.push(`<div class="heat-cell" data-lang="${l.code}" data-cat="${c.key}"
        style="background:var(--seq-${k});color:${k >= 4 ? "var(--paper)" : "var(--ink)"}">${Math.round(v * 100)}</div>`);
    }
  }
  el.innerHTML = html.join("");
  el.querySelectorAll(".heat-cell").forEach((cellEl) => {
    const s = cell.get(`${cellEl.dataset.lang}|${cellEl.dataset.cat}`);
    const l = langBy(cellEl.dataset.lang);
    cellEl.addEventListener("mousemove", (e) =>
      showTip(`<b>${esc(l.name)} · ${esc(catLabel(cellEl.dataset.cat))}</b><br>${s.present} of ${s.topics} topics have an article (${pct(s.coverage)})<br>Access score ${s.access.toFixed(0)}`, e));
    cellEl.addEventListener("mouseleave", hideTip);
  });
  $("#heat-legend").innerHTML = `<span>0%</span><span class="ramp">${[0, 1, 2, 3, 4, 5, 6].map((k) => `<span style="background:var(--seq-${k})"></span>`).join("")}</span><span>100% of topics have an article</span>`;
}

// ---------- section 3: language panel ----------
function priorityFor(code) {
  return TOPICS
    .map((t) => ({ t, s: t.s[code] }))
    .filter(({ s }) => !s || s[0] === 1)
    .sort((a, b) => b.t.v - a.t.v)
    .map(({ t, s }) => ({ qid: t.q, title: t.t, views: t.v, status: s ? "stub" : "missing", local: s ? s[2] : "" , cats: t.c }));
}

function renderLanguage(code, showAll = false) {
  const l = langBy(code);
  const list = priorityFor(code);
  const shown = showAll ? list.slice(0, 100) : list.slice(0, 20);
  const catRows = DATA.categories.map((c) => {
    const s = DATA.categoryScores.find((x) => x.lang === code && x.category === c.key);
    const v = s ? s.coverage : 0;
    return `<span>${esc(c.label)}</span><span class="track"><span class="fill" style="width:${v * 100}%"></span></span><span class="val">${pct(v)}</span>`;
  }).join("");

  $("#lang-panel").innerHTML = `
    <h3>${esc(l.name)}<span class="native" lang="${l.code}">${esc(l.native)}</span></h3>
    <div class="statline">
      <span><b>${l.access.toFixed(0)}</b>access score</span>
      <span><b>${l.present}</b>of ${l.topics} topics</span>
      <span><b>${l.stubs}</b>stubs</span>
      <span><b>${l.missing}</b>missing</span>
      <span><b>${pct(l.fresh || 0)}</b>edited this year</span>
    </div>
    <div class="cat-bars" aria-label="Coverage by area">${catRows}</div>
    <div class="row-actions">
      <strong>${list.length ? `Write these first (${list.length} missing or stubs)` : "Nothing missing. Every topic has a real article."}</strong>
      ${list.length ? `<button class="linkbtn" id="dl">Download the full list (CSV)</button>` : ""}
    </div>
    <ol class="priority">${shown.map((p) => `
      <li><span><a href="${wikiUrl("en", p.title)}" target="_blank" rel="noopener">${esc(p.title)}</a>
        <span class="tag ${p.status}">${STATUS_LABEL[p.status]}</span>
        ${p.local ? ` <a href="${wikiUrl(code, p.local)}" target="_blank" rel="noopener" lang="${code}" style="font-family:var(--indic)">${esc(p.local)}</a>` : ""}</span>
        <span class="reads">${indianNumber(p.views)} reads</span></li>`).join("")}
    </ol>
    ${list.length > 20 && !showAll ? `<p><button class="linkbtn" id="more">Show the top 100</button></p>` : ""}`;

  $("#more")?.addEventListener("click", () => renderLanguage(code, true));
  $("#dl")?.addEventListener("click", () => downloadCsv(code, list));
}

function downloadCsv(code, list) {
  const rows = [["rank", "english_title", "status", "existing_title", "english_views_12m", "categories", "wikidata_id"]];
  list.forEach((p, i) => rows.push([i + 1, p.title, p.status, p.local, p.views, p.cats.join(";"), p.qid]));
  const csv = rows.map((r) => r.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `bhashagap-priorities-${code}.csv` });
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---------- section 4: topic lookup ----------
function renderSearch(q) {
  const out = $("#topic-results");
  q = q.trim().toLowerCase();
  if (q.length < 2) { out.innerHTML = ""; return; }
  const hits = TOPICS.filter((t) => t.t.toLowerCase().includes(q)).slice(0, 8);
  out.innerHTML = hits.length
    ? hits.map((t) => `<li><button data-q="${t.q}">${esc(t.t)}<span class="cat">${esc(t.c.map(catLabel).join(", "))}</span></button></li>`).join("")
    : `<li class="small">No topic matches “${esc(q)}”. The list covers ${TOPICS.length} topics.</li>`;
  out.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => renderTopic(b.dataset.q)));
}

function renderTopic(qid) {
  const t = TOPICS.find((x) => x.q === qid);
  const have = DATA.languages.filter((l) => t.s[l.code]).length;
  const items = DATA.languages.map((l) => {
    const s = t.s[l.code];
    const status = s ? STATUS[s[0]] : "missing";
    const title = s ? `<a href="${wikiUrl(l.code, s[2])}" target="_blank" rel="noopener" lang="${l.code}">${esc(s[2])}</a>` : `<span class="small">no article</span>`;
    return `<div class="item"><span>${esc(l.name)}</span>${title}<span class="tag ${status}">${status}</span></div>`;
  }).join("");
  $("#topic-detail").innerHTML = `
    <div class="topic-card">
      <h3><a href="${wikiUrl("en", t.t)}" target="_blank" rel="noopener">${esc(t.t)}</a></h3>
      <p class="small">${esc(t.c.map(catLabel).join(", "))} · ${indianNumber(t.v)} English reads in 12 months ·
        available in ${have} of ${DATA.languages.length} languages</p>
      <div class="lang-grid">${items}</div>
    </div>`;
  $("#topic-results").innerHTML = "";
}

// ---------- boot ----------
async function main() {
  try {
    const [summary, topics] = await Promise.all([fetch("data/summary.json").then((r) => r.json()), fetch("data/topics.json").then((r) => r.json())]);
    DATA = summary;
    TOPICS = topics;
  } catch (err) {
    $("#lede").textContent = "Couldn't load the data. Serve this folder over HTTP (python3 -m http.server) rather than opening the file directly.";
    return;
  }
  renderIntro();
  renderBars("access");
  document.querySelectorAll(".controls button").forEach((b) => b.addEventListener("click", () => renderBars(b.dataset.metric)));
  renderHeatmap();

  const select = $("#lang-select");
  select.innerHTML = DATA.languages.map((l) => `<option value="${l.code}">${esc(l.name)} (${esc(l.native)})</option>`).join("");
  const initial = DATA.languages.find((l) => l.code === "mr") ? "mr" : DATA.languages[0].code;
  select.value = initial;
  renderLanguage(initial);
  select.addEventListener("change", () => renderLanguage(select.value));

  const search = $("#topic-search");
  search.addEventListener("input", () => renderSearch(search.value));
}

main();
