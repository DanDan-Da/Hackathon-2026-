// RuleCheck findings UI. No build step, no remote scripts. All data is rendered with textContent.
"use strict";

const STATUS = {
  fail:           { label: "Fail",           icon: "✕", order: 0 },
  needs_review:   { label: "Needs review",   icon: "?",      order: 1 },
  pass:           { label: "Pass",           icon: "✓", order: 2 },
  not_applicable: { label: "Not applicable", icon: "–", order: 3 },
};
const $ = (id) => document.getElementById(id);
const state = { findings: [], rules: {}, active: new Set(Object.keys(STATUS)), regime: "", selected: null, factsLoading: null };

function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) n.append(k);
  return n;
}
const badge = (s) => el("span", { class: "badge " + s }, el("span", { "aria-hidden": "true" }, STATUS[s].icon), STATUS[s].label);

function say(text, err) { const m = $("msg"); m.textContent = text; m.className = "msg" + (err ? " err" : ""); }

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let d = r.statusText;
    try { const j = await r.json(); d = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) {}
    throw new Error(`${r.status}: ${d}`);
  }
  return r;
}

function parseJson(text, what) {
  try { return JSON.parse(text); } catch (e) { throw new Error(`${what} is not valid JSON (${e.message})`); }
}

async function run() {
  showTab("check");
  say("Checking...");
  try {
    await state.factsLoading;   // a file picked a moment ago may still be loading
    const facts = parseJson($("facts-text").value, "Facts");
    const body = { facts, ship_type: $("ship-type").value };
    const own = document.querySelector("input[name=rules-src]:checked").value === "own";
    if (own) body.rules = parseJson($("rules-text").value, "Rules");
    const res = await (await api("/ui/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
    state.rules = {};
    try {
      const rules = own ? body.rules : await (await api("/rules")).json();
      for (const r of rules) state.rules[r.id] = r;
    } catch (_) { /* titles are optional */ }
    show(res);
    loadTrust();
    say(`${res.length} findings.`);
  } catch (e) { say(e.message, true); }
}

async function demo() {
  say("Loading demo...");
  try {
    const d = await (await api("/ui/demo")).json();
    $("facts-pick").value = "";   // the picker must not name a file that is no longer loaded
    $("facts-text").value = JSON.stringify(d.facts, null, 2);
    $("rules-text").value = JSON.stringify(d.rules, null, 2);
    document.querySelector("input[name=rules-src][value=own]").checked = true;
    $("rules-own").hidden = false;
    await run();
  } catch (e) { say(e.message, true); }
}

function show(findings) {
  state.findings = findings.map((f, i) => ({ ...f, _i: i }));
  state.active = new Set(Object.keys(STATUS));
  state.regime = "";
  state.selected = null;
  $("empty").hidden = true; $("results").hidden = false;
  const regimes = [...new Set(findings.map((f) => f.rule_source.regime))].sort();
  const sel = $("regime");
  sel.replaceChildren(el("option", { value: "" }, "All"), ...regimes.map((r) => el("option", { value: r }, r)));
  render();
}

const LOW_CONF_DEFAULT = 0.6;
const trustInfo = { threshold: LOW_CONF_DEFAULT, eval: undefined, statement: "" };

async function loadTrust() {
  try {
    const t = await (await api("/ui/trust")).json();
    trustInfo.threshold = t.low_confidence_threshold; trustInfo.eval = t.eval; trustInfo.statement = t.statement;
  } catch (_) { trustInfo.eval = undefined; }
  renderTrust();
}

// Counts for the scoreboard, from the findings on screen (all computed, none stored).
function trustStats(findings) {
  const decided = findings.filter((f) => f.status !== "not_applicable");
  const low = decided.filter((f) => f.evidence.some((p) => p.confidence < trustInfo.threshold));
  const cited = decided.filter((f) => f.rule_source && f.rule_source.quote && f.evidence.length > 0);
  return { n: findings.length, decided: decided.length, low: low.length, cited: cited.length };
}

function renderTrust() {
  const all = state.findings, s = trustStats(all);
  const cnt = (k) => all.filter((f) => f.status === k).length;
  const row = (label, value, note) => [el("dt", {}, label), el("dd", {}, el("b", {}, value), note ? el("span", { class: "note" }, " " + note) : null)];
  const e = trustInfo.eval;
  const rows = [
    ...row("By status", `${cnt("fail")} fail, ${cnt("needs_review")} needs review, ${cnt("pass")} pass, ${cnt("not_applicable")} not applicable`),
    ...row("On low-confidence evidence", s.decided ? `${s.low} of ${s.decided} (${Math.round(100 * s.low / s.decided)}%)` : "none",
      `evidence read with confidence below ${Math.round(trustInfo.threshold * 100)}%; the checker returns needs review for these`),
    ...row("Cite rule quote and design location", `${s.cited} of ${s.decided}`,
      s.cited === s.decided ? "every decided finding has both" : "some findings are missing a side; treat them as unverified"),
    ...row("Planted-violation test", e === undefined ? "loading" : e === null ? "not available" : `${e.correct} of ${e.total} correct`,
      e ? `${e.missed_violations} missed violations, ${e.false_alarms} false alarms (run live on the mock design)` : ""),
  ];
  $("trust").replaceChildren(...rows);
  $("trust-line").textContent = trustInfo.statement || "Anything not provable is marked needs review, never guessed.";
}

function visible() {
  return state.findings
    .filter((f) => state.active.has(f.status) && (!state.regime || f.rule_source.regime === state.regime))
    .sort((a, b) => STATUS[a.status].order - STATUS[b.status].order || a.rule_id.localeCompare(b.rule_id) || (a.element_id || "").localeCompare(b.element_id || ""));
}

function render() {
  const all = state.findings;
  const n = (s) => all.filter((f) => f.status === s).length;
  $("counts").replaceChildren(...["fail", "needs_review", "pass"].map((s) =>
    el("div", { class: "count " + s }, el("b", {}, String(n(s))), el("span", {}, STATUS[s].label.toLowerCase()))));
  const na = n("not_applicable");
  if (na) $("counts").append(el("div", { class: "count" }, el("b", {}, String(na)), el("span", {}, "not applicable")));
  const bar = $("bar");
  bar.setAttribute("aria-label", Object.keys(STATUS).map((s) => `${n(s)} ${STATUS[s].label}`).join(", "));
  bar.replaceChildren(...Object.keys(STATUS).filter(n).map((s) => { const i = el("i", { class: s }); i.style.width = (100 * n(s) / all.length) + "%"; return i; }));

  $("status-filters").replaceChildren(...Object.keys(STATUS).map((s) => {
    const b = el("button", { class: "chip", "aria-pressed": String(state.active.has(s)), type: "button" }, `${STATUS[s].label} (${n(s)})`);
    b.addEventListener("click", () => { state.active.has(s) ? state.active.delete(s) : state.active.add(s); render(); });
    return b;
  }));

  const rows = visible();
  $("shown").textContent = `Showing ${rows.length} of ${all.length}. Fails first, then needs review.`;
  if (!rows.some((f) => f._i === state.selected)) state.selected = rows.length ? rows[0]._i : null;
  $("list").replaceChildren(...rows.map((f) => {
    const rule = state.rules[f.rule_id];
    const b = el("button", { class: "item " + f.status, type: "button", "aria-current": String(f._i === state.selected) },
      badge(f.status),
      el("span", { class: "t" }, rule ? rule.title : f.rule_id),
      el("span", { class: "s" }, `${f.rule_source.regime} ${f.rule_source.clause || ""}${f.element_id ? " • " + f.element_id : ""}`));
    b.addEventListener("click", () => { state.selected = f._i; render(); });
    return el("li", {}, b);
  }));
  renderTrust();
  detail(state.findings.find((f) => f._i === state.selected));
}

function provLine(p) {
  const parts = [`file ${p.file}`];
  if (p.page != null) parts.push(`page ${p.page}`);
  if (p.element_id) parts.push(`element ${p.element_id}`);
  parts.push(`${p.method}, confidence ${Math.round(p.confidence * 100)}%`);
  return parts.join(", ");
}

const AUTO_CROPS = 2;   // show this many drawing crops straight away; the rest load on click

function evidenceBox(p, index = 0) {
  const box = el("div", { class: "ev" }, el("div", {}, provLine(p)));
  if (p.page != null && p.bbox) {
    const shown = p.bbox.map((v) => Math.round(v)).join(", ");   // display only; the crop uses exact values
    box.append(el("div", {}, `Page ${p.page}, bbox (PDF points) `, el("code", {}, shown)));
    const out = el("div");
    const btn = el("button", { type: "button" }, "Show drawing crop");
    const load = async () => {
      btn.disabled = true;
      try {
        const av = await (await api("/ui/evidence-available?" + new URLSearchParams({ file: p.file }))).json();
        if (!av.available) {
          out.replaceChildren(el("p", { class: "note" }, "Drawing not available in this demo (the file is not on this server)."));
          btn.remove();
          return;
        }
        const q =new URLSearchParams({ file: p.file, page: p.page, bbox: p.bbox.join(",") });
        const blob = await (await api("/evidence/crop?" + q)).blob();
        out.replaceChildren(el("img", { src: URL.createObjectURL(blob), alt: `Drawing page ${p.page} around bbox ${shown}; the evidence is outlined in red` }));
        btn.remove();
      } catch (e) {
        out.replaceChildren(el("p", { class: "note" }, `Crop not available: ${e.message}. The file must be a PDF inside the designs folder.`));
        btn.disabled = false;
      }
    };
    btn.addEventListener("click", load);
    box.append(btn, out);
    if (index < AUTO_CROPS) load();
  } else if (p.page != null) {
    box.append(el("div", { class: "note" }, "No bbox recorded for this fact."));
  }
  return box;
}

function detail(f) {
  const d = $("detail");
  d.className = "detail" + (f && f.status === "needs_review" ? " needs_review" : "");
  if (!f) { d.replaceChildren(el("p", { class: "note" }, "No finding matches the current filters.")); return; }
  const rule = state.rules[f.rule_id], src = f.rule_source;
  const kids = [badge(f.status), el("h3", {}, rule ? rule.title : f.rule_id)];
  if (f.status === "needs_review")
    kids.push(el("div", { class: "alert" }, "Not decided. The evidence is missing or too uncertain, so a person has to check this."));

  kids.push(el("h4", {}, "Why this status"), el("p", {}, f.message));
  if (f.reasoning) kids.push(el("p", {}, f.reasoning));
  kids.push(el("p", { class: "note" }, f.method === "llm_judge" ? "Judged by the language model, output structured and cited." : "Checked deterministically."));

  if (f.remedy) {
    kids.push(el("h4", {}, "What would make it pass"), el("p", { class: "remedy" }, f.remedy.text),
      el("p", { class: "note" }, "Computed from the rule and the measured value; it is the smallest change that satisfies this rule alone."));
  }

  if (f.measured != null || f.required) {
    kids.push(el("h4", {}, "Measured and required"), el("dl", { class: "cmp" },
      el("dt", {}, "Measured"), el("dd", {}, f.measured != null ? String(f.measured) : "not found"),
      el("dt", {}, "Required"), el("dd", {}, f.required || "-")));
    kids.push(el("p", { class: "note" }, "Measured values are in internal base units (lengths in mm, areas in m²); the required value shows the rule's own unit."));
  }

  kids.push(el("h4", {}, "Rule"),
    el("p", { class: "cite" }, `${src.regime}, ${src.document}${src.page != null ? ", page " + src.page : ""}${src.clause ? ", clause " + src.clause : ""}`),
    el("blockquote", {}, src.quote));

  kids.push(el("h4", {}, `Design evidence${f.element_id ? " for " + f.element_id : ""}`));
  if (f.evidence.length) kids.push(...f.evidence.map((p, i) => evidenceBox(p, i)));
  else kids.push(el("p", { class: "note" }, "No design evidence attached to this finding."));
  d.replaceChildren(...kids);
}

function readInto(input, target) {
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (file) target.value = await file.text();
  });
}

// ---- design facts from the designs folder ----
async function loadFactsList() {
  try {
    const list = await (await api("/ui/facts")).json();
    $("facts-pick").replaceChildren(el("option", { value: "" }, "Choose..."), ...list.map((f) => el("option", { value: f.name }, `${f.name} (${f.project})`)));
    $("facts-pick-note").textContent = list.length ? "" : "No design facts found in the designs folder. Load the demo or open a file.";
  } catch (e) { $("facts-pick-note").textContent = "Could not list the designs folder."; }
}
$("facts-pick").addEventListener("change", (e) => {
  if (!e.target.value) return;
  const name = e.target.value;
  // A design from the designs folder is checked against the server's compiled rules, not
  // against rules left in the box by "Load demo".
  document.querySelector("input[name=rules-src][value=server]").checked = true;
  $("rules-own").hidden = true;
  say(`Loading ${name}...`);
  state.factsLoading = (async () => {
    try {
      const f = await (await api("/ui/facts/load?" + new URLSearchParams({ name }))).json();
      $("facts-text").value = JSON.stringify(f, null, 2);
      say(`Loaded ${name}. Press Run check.`);
    } catch (err) { say(err.message, true); }
  })();
});

// ---- panels ----
// Plain-language message for a failed call: never a stack trace or a bare status line.
function plain(e) {
  const m = String(e.message || e);
  if (/^500:/.test(m)) return "The server hit an error while doing this (see the server log). Nothing was changed.";
  if (/Failed to fetch|NetworkError/.test(m)) return "The API is not reachable.";
  return m;
}
function setMsg(id, text, err) { const m = $(id); m.textContent = text; m.className = "msg" + (err ? " err" : ""); }

function showTab(name) {
  document.querySelectorAll(".tab").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tab === name)));
  for (const t of ["check", "rules", "ask", "add"]) $("tab-" + t).hidden = t !== name;
  if (name === "rules") loadRulesPanel();
}
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

function ruleCard(r) {
  const card = el("li", { class: "rule" + (r.reviewed ? " reviewed" : "") });
  const flag = el("span", { class: "badge " + (r.reviewed ? "pass" : "needs_review") }, r.reviewed ? "Reviewed by a person" : "Not reviewed (AI-compiled)");
  const src = r.source || {};
  const fields = ["target", "parameter", "value", "unit"];
  const inputs = {};
  const form = el("form");
  for (const f of fields) {
    inputs[f] = el("input", { type: "text", id: `rule-${r.id}-${f}`, value: r[f] == null ? "" : String(r[f]) });
    form.append(el("label", { for: `rule-${r.id}-${f}` }, f, inputs[f]));
  }
  const msg = el("span", { class: "note", role: "status" });
  const save = async (reviewedOnly) => {
    const body = {};
    if (reviewedOnly) body.reviewed = true;
    else for (const f of fields) {
      const v = inputs[f].value.trim();
      if (v === String(r[f] == null ? "" : r[f])) continue;
      body[f] = v === "" ? null : (f === "value" && v !== "" && !isNaN(Number(v)) ? Number(v) : v);
    }
    if (!Object.keys(body).length) { msg.textContent = "No changes."; return; }
    try {
      const upd = await (await api("/rules/" + encodeURIComponent(r.id), { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
      card.replaceWith(ruleCard(upd));
    } catch (e) { msg.textContent = plain(e).replace(/^404:.*/, "This rule no longer exists; reload the list."); msg.className = "note err"; }
  };
  const bSave = el("button", { type: "button", class: "primary" }, "Save edit (marks reviewed)");
  bSave.addEventListener("click", () => save(false));
  form.append(el("div", { class: "row" }, bSave));
  if (!r.reviewed) {
    const bRev = el("button", { type: "button" }, "I have checked this rule: mark reviewed");
    bRev.addEventListener("click", () => save(true));
    form.lastChild.append(bRev);
  }
  form.lastChild.append(msg);
  form.addEventListener("submit", (e) => e.preventDefault());
  card.append(el("h3", {}, r.title || r.id), flag,
    el("p", { class: "meta" }, `${src.regime || "?"}, ${src.document || ""}${src.page != null ? ", page " + src.page : ""}${src.clause ? ", clause " + src.clause : ""}`),
    el("blockquote", {}, src.quote || ""), form);
  return card;
}

async function loadRulesPanel() {
  const list = $("rules-list");
  setMsg("rules-msg", "Loading...");
  try {
    const rules = await (await api("/rules")).json();
    list.replaceChildren(...rules.map(ruleCard));
    const n = rules.filter((r) => r.reviewed).length;
    setMsg("rules-msg", rules.length ? `${rules.length} rules, ${n} reviewed by a person.` : "The rules file is empty. Add a regulation and compile it.");
  } catch (e) {
    list.replaceChildren();
    setMsg("rules-msg", /^404:/.test(e.message) ? "No compiled rules yet. Use Add a regulation to compile some." : plain(e), !/^404:/.test(e.message));
  }
}

function sourceBlock(s) {
  return el("li", {}, el("div", { class: "cite" }, `${s.regime}, ${s.document}${s.page != null ? ", page " + s.page : ""}${s.clause ? ", clause " + s.clause : ""}`), el("blockquote", {}, s.quote));
}

async function askQuestion() {
  const q = $("ask-q").value.trim(), out = $("ask-out");
  out.replaceChildren();
  if (q.length < 3) { setMsg("ask-msg", "Type a question first.", true); return; }
  setMsg("ask-msg", "Asking...");
  $("ask-go").disabled = true;
  try {
    const body = { question: q }, rg = $("ask-regime").value.trim();
    if (rg) body.regime = rg;
    const a = await (await api("/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
    const kids = [];
    if (a.status === "answered") {
      setMsg("ask-msg", "Answer with verified citations.");
      kids.push(el("p", { class: "answer" }, a.answer), el("h4", {}, "Citations (checked to be verbatim)"), el("ul", { class: "cites" }, ...a.citations.map(sourceBlock)));
    } else {
      const why = {
        llm_unavailable: "The AI is not available right now (no key or quota used up), so there is no written answer. The passages found are shown instead.",
        needs_review: "The AI gave no citation that could be verified, so its answer was withheld. A person should read the passages below.",
        no_sources: "Nothing in the regulation index matched the question.",
      }[a.status] || "No answer.";
      setMsg("ask-msg", why, true);
      if (a.note) kids.push(el("p", { class: "note" }, a.note));
    }
    if (a.passages && a.passages.length && a.status !== "answered")
      kids.push(el("h4", {}, "Passages found"), el("ul", { class: "cites" }, ...a.passages.map(sourceBlock)));
    out.replaceChildren(...kids);
  } catch (e) {
    const m = String(e.message);
    setMsg("ask-msg", /^503:/.test(m) ? "The regulation index is not set up on this server (needs the 'rag' extra and a built index)."
      : /^500:/.test(m) ? "The regulation index is missing or could not be read. Build it first (python -m app.ingest.index)." : plain(e), true);
  } finally { $("ask-go").disabled = false; }
}
$("ask-go").addEventListener("click", askQuestion);

$("add-save").addEventListener("click", async () => {
  const regime = $("add-regime").value.trim(), file = $("add-file").files[0];
  if (!regime || !file) { setMsg("add-msg", "Enter a regime and choose a file.", true); return; }
  setMsg("add-msg", "Saving...");
  try {
    const r = await (await api("/ui/regulations?" + new URLSearchParams({ regime, filename: file.name }), { method: "POST", body: file })).json();
    setMsg("add-msg", `Saved as ${r.saved} (${r.bytes} bytes). Now compile it below.`);
    $("ingest-regime").value = regime;
  } catch (e) { setMsg("add-msg", plain(e), true); }
});

$("ingest-go").addEventListener("click", async () => {
  const rg = $("ingest-regime").value.trim();
  if (!rg && !window.confirm("Compile ALL regimes? This uses a lot of AI quota and takes minutes.")) return;
  setMsg("ingest-msg", "Compiling with AI... this can take minutes.");
  $("ingest-go").disabled = true;
  try {
    const r = await (await api("/ingest/rules" + (rg ? "?" + new URLSearchParams({ regime: rg }) : ""), { method: "POST" })).json();
    setMsg("ingest-msg", `Done: ${r.rules} rules in total, ${r.reviewed} already reviewed by a person. Open the Rules tab to review them.`);
  } catch (e) {
    setMsg("ingest-msg", `Compiling failed (no AI key, quota used up, or a bad file). Existing rules were kept. ${/^500:/.test(e.message) ? "See the server log for the reason." : plain(e)}`, true);
  } finally { $("ingest-go").disabled = false; }
});

$("regime").addEventListener("change", (e) => { state.regime = e.target.value; render(); });
document.querySelectorAll("input[name=rules-src]").forEach((r) => r.addEventListener("change", () => {
  $("rules-own").hidden = document.querySelector("input[name=rules-src]:checked").value !== "own";
}));
readInto($("facts-file"), $("facts-text"));
readInto($("rules-file"), $("rules-text"));
$("run").addEventListener("click", run);
$("demo").addEventListener("click", demo);
loadFactsList();
api("/ui/regimes").then((r) => r.json()).then((list) => {
  $("regime-list").replaceChildren(...list.map((r) => el("option", { value: r })));
}).catch(() => { /* suggestions are optional */ });
api("/health").then((r) => r.json()).then((h) => { $("health").textContent = `API ok, provider ${h.provider}`; })
  .catch(() => { $("health").textContent = "API not reachable"; });
