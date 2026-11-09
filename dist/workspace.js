/* Demo Ventures workspace (analyst.html): one section per sidebar item.
 * Access: every section and button follows the signed-in person's permissions (TAB_PERMS mirrors
 * backend/permissions.py). Hiding is cosmetic; the server checks every request.
 */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const $ = (id) => document.getElementById(id);
const fmt = (iso) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "-");
const STATUS_LABEL = { queued: "Queued", assigned: "Assigned", in_progress: "In progress", resolved: "Resolved" };
const RES_LABEL = { in_review: "Waiting for approval", approved: "Approved", rejected: "Returned for changes", archived: "Withdrawn" };
const RES_CLASS = { in_review: "review", approved: "resolved", rejected: "upcoming", archived: "upcoming" };
let contentFilter = "in_review";

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2600);
}

/* ---------------- Work queue */
/* Inline editor used instead of browser pop-ups: opens a small form under the row it belongs to.
   Resolves with the trimmed text, or null when cancelled. */
function askInline(anchor, { label, value = "", placeholder = "", required = false, multiline = false, save = "Save", hint = "" }) {
  return new Promise((resolve) => {
    document.querySelectorAll(".inline-ask").forEach((n) => n.remove());
    const tr = anchor.closest("tr");
    const host = document.createElement(tr ? "tr" : "div");
    host.className = "inline-ask";
    const field = multiline
      ? `<textarea id="inline-ask-input" rows="3" maxlength="600" placeholder="${esc(placeholder)}"></textarea>`
      : `<input id="inline-ask-input" maxlength="500" placeholder="${esc(placeholder)}">`;
    const inner = `<form class="inline-ask-form"><label for="inline-ask-input">${esc(label)}</label>${field}${hint ? `<small class="muted">${esc(hint)}</small>` : ""}<div class="row-actions"><button class="btn primary" type="submit">${esc(save)}</button><button class="btn ghost" type="button" data-cancel>Cancel</button></div></form>`;
    host.innerHTML = tr ? `<td colspan="${tr.children.length}">${inner}</td>` : inner;
    (tr || anchor.closest(".person, .approval-row, article, .card") || anchor).after(host);
    const form = host.querySelector("form");
    const input = form.querySelector("#inline-ask-input");
    input.value = value;
    input.focus();
    const done = (v) => { host.remove(); resolve(v); };
    form.onsubmit = (e) => {
      e.preventDefault();
      const v = input.value.trim();
      if (required && !v) { input.focus(); toast(`${label}: this is required`); return; }
      done(v);
    };
    form.querySelector("[data-cancel]").onclick = () => done(null);
    input.onkeydown = (e) => { if (e.key === "Escape") done(null); };
  });
}

/* Inline edit form for a whole record (company details, an event, a Connect profile). Opens under the row
   or card it belongs to; onSave(FormData) returns true when saved, which closes the form. */
function editForm(anchor, title, fieldsHtml, saveLabel, onSave) {
  document.querySelectorAll(".inline-edit").forEach((n) => n.remove());
  const tr = anchor.closest("tr");
  const host = document.createElement(tr ? "tr" : "div");
  host.className = "inline-edit";
  const inner = `<form class="review-form inline-edit-form"><h4 class="full" style="margin:0">${esc(title)}</h4>${fieldsHtml}<div class="full review-actions"><button class="btn primary" type="submit">${esc(saveLabel)}</button><button class="btn ghost" type="button" data-cancel>Cancel</button></div></form>`;
  host.innerHTML = tr ? `<td colspan="${tr.children.length}">${inner}</td>` : `<div class="card" style="margin:.75rem 0">${inner}</div>`;
  (tr || anchor.closest(".person, article, .card") || anchor).after(host);
  const form = host.querySelector("form");
  wireAudience(form);
  wireWhen(form);
  form.querySelector("input, select, textarea")?.focus();
  form.querySelector("[data-cancel]").onclick = () => host.remove();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector("[type=submit]");
    btn.disabled = true;
    try {
      if (await onSave(new FormData(form))) host.remove();
    } finally {
      btn.disabled = false;
    }
  };
}
/* ---------------- Form helpers (partner review, 4 Nov 2026)
   helpTip(text): a "?" next to a field label that explains the field on hover, focus or tap.
   multiPick(attrs, options, selected, placeholder): a compact dropdown of checkboxes with a search box, used
   instead of long checkbox walls (funds, sectors, stages, companies, tags). `attrs` goes on every checkbox,
   e.g. 'name="fund"' or 'data-aud-sector', so FormData.getAll() and the audience reader keep working. */
const FUNDS = ["Fund I", "Fund II", "Fund III", "Fund IV"];
const RESOURCE_TAGS = ["Template", "Checklist", "Guide", "Playbook", "Policy", "Tracker", "Report", "Board", "Governance", "Compliance",
  "Legal", "Tax", "Finance", "MIS", "KPIs", "Fundraising", "Investor relations", "Pitch deck", "Data room", "Cap table", "Valuation",
  "Sales", "Marketing", "Product", "Technology", "Operations", "Hiring", "HR", "ESOP", "ESG", "Market entry", "UAE"];
const tagOptions = (extra = []) => [...new Set([...RESOURCE_TAGS, ...[...contentById.values()].flatMap((r) => r.tags || []), ...extra])].sort((a, b) => a.localeCompare(b));
const helpTip = (text) => `<button type="button" class="help-tip" aria-label="${esc(text)}" data-tip="${esc(text)}">?</button>`;
function multiPick(attrs, options, selected = [], placeholder = "Choose…") {
  const chosen = new Set((selected || []).map(String));
  const opts = options.map((o) => (typeof o === "object" ? o : { value: o, label: o }));
  return `<div class="mpick" data-mpick data-placeholder="${esc(placeholder)}"><button type="button" class="mpick-btn" aria-haspopup="true" aria-expanded="false"><span data-mpick-label></span><span aria-hidden="true">▾</span></button>
    <div class="mpick-pop hidden">${opts.length > 8 ? `<input type="search" class="mpick-search" placeholder="Search" aria-label="Search the list">` : ""}
      <div class="mpick-list">${opts.map((o) => `<label class="check"><input type="checkbox" ${attrs} value="${esc(o.value)}"${chosen.has(String(o.value)) ? " checked" : ""}> ${esc(o.label)}</label>`).join("") || `<span class="muted">Nothing to choose yet.</span>`}</div>
      <div class="mpick-foot"><button type="button" class="text-btn" data-mpick-clear>Clear</button><button type="button" class="btn ghost" data-mpick-done>Done</button></div></div></div>`;
}
function mpickLabel(box) {
  const ticked = [...box.querySelectorAll(".mpick-list input:checked")].map((i) => i.closest("label").textContent.trim());
  const text = ticked.length ? (ticked.length <= 3 ? ticked.join(", ") : `${ticked.slice(0, 2).join(", ")} and ${ticked.length - 2} more`) : box.dataset.placeholder;
  const span = box.querySelector("[data-mpick-label]");
  if (span.textContent !== text) span.textContent = text; // only on a real change, so the page observer does not loop
}
function wireMultiPicks(root = document) {
  root.querySelectorAll("[data-mpick]").forEach(mpickLabel);
}
document.addEventListener("click", (e) => {
  const box = e.target.closest("[data-mpick]");
  document.querySelectorAll("[data-mpick] .mpick-pop:not(.hidden)").forEach((pop) => {
    if (!box || pop.closest("[data-mpick]") !== box) { pop.classList.add("hidden"); pop.closest("[data-mpick]").querySelector(".mpick-btn").setAttribute("aria-expanded", "false"); }
  });
  if (!box) return;
  const pop = box.querySelector(".mpick-pop");
  if (e.target.closest(".mpick-btn")) {
    const open = pop.classList.toggle("hidden") === false;
    box.querySelector(".mpick-btn").setAttribute("aria-expanded", String(open));
    if (open) pop.querySelector(".mpick-search")?.focus();
  } else if (e.target.closest("[data-mpick-done]")) {
    pop.classList.add("hidden");
    box.querySelector(".mpick-btn").setAttribute("aria-expanded", "false");
  } else if (e.target.closest("[data-mpick-clear]")) {
    box.querySelectorAll(".mpick-list input:checked").forEach((i) => { i.checked = false; });
    mpickLabel(box);
    box.dispatchEvent(new Event("change", { bubbles: true }));
  }
});
document.addEventListener("change", (e) => { const box = e.target.closest("[data-mpick]"); if (box) mpickLabel(box); });
document.addEventListener("input", (e) => {
  if (!e.target.classList.contains("mpick-search")) return;
  const q = e.target.value.trim().toLowerCase();
  e.target.closest("[data-mpick]").querySelectorAll(".mpick-list label").forEach((l) => l.classList.toggle("hidden", !!q && !l.textContent.toLowerCase().includes(q)));
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  document.querySelectorAll("[data-mpick] .mpick-pop:not(.hidden)").forEach((pop) => pop.classList.add("hidden"));
});
// Re-label pickers whenever new forms are drawn.
new MutationObserver(() => wireMultiPicks()).observe(document.documentElement, { childList: true, subtree: true });

// ISO time -> value for <input type="datetime-local"> in IST.
const istInput = (iso) => (iso ? new Date(iso).toLocaleString("sv-SE", { timeZone: "Asia/Kolkata" }).replace(" ", "T").slice(0, 16) : "");


/* ---------------- Audience picker (meetings 23 Oct): who a resource, event, update or message is for.
   Modes: all portfolio companies, one company, chosen companies, or by sector and/or stage. Shows how many
   companies match before saving. readAudience() returns the API shape {company_id, target_*}. */
let audOpts = null;
async function loadAudienceOptions(force) {
  if (!audOpts || force) audOpts = await PortalAPI.json("/api/admin/audience-options");
  return audOpts;
}
const sectorTags = (text) => String(text || "").split(",").map((t) => t.trim()).filter(Boolean);
function audienceMode(cur = {}) {
  if (cur.company_id) return "one";
  if ((cur.target_company_ids || []).length) return "companies";
  if ((cur.target_sectors || []).length || (cur.target_stages || []).length) return "segment";
  return "all";
}
function audiencePicker(cur = {}, label = "Who it is for") {
  const o = audOpts || { companies: [], sectors: [], stages: [] };
  const mode = audienceMode(cur);
  const chosen = new Set(cur.target_company_ids || []);
  const secs = new Set(cur.target_sectors || []);
  const stages = new Set(cur.target_stages || []);
  const box = (name, value, on, text) => `<label class="check"><input type="checkbox" data-aud-${name} value="${esc(value)}"${on ? " checked" : ""}> ${esc(text)}</label>`;
  return `<fieldset class="full audience" data-aud>
    <legend>${esc(label)}</legend>
    <label>Send to<select data-aud-mode>
      <option value="all"${mode === "all" ? " selected" : ""}>All portfolio companies</option>
      <option value="one"${mode === "one" ? " selected" : ""}>One company</option>
      <option value="companies"${mode === "companies" ? " selected" : ""}>Chosen companies</option>
      <option value="segment"${mode === "segment" ? " selected" : ""}>By sector and/or stage</option>
    </select></label>
    <label data-aud-show="one">Company<select data-aud-company>${o.companies.map((c) => `<option value="${c.id}"${c.id === cur.company_id ? " selected" : ""}>${esc(c.name)}${c.status === "exited" ? " (exited)" : ""}</option>`).join("")}</select></label>
    <label data-aud-show="companies">Companies${multiPick("data-aud-co", o.companies.map((c) => ({ value: c.id, label: c.name })), [...chosen], "Choose companies")}</label>
    <div data-aud-show="segment" class="aud-segment"><label>Sectors <small class="muted">(any of these)</small>${multiPick("data-aud-sector", o.sectors, [...secs], "Any sector")}</label>
      <label>Stages <small class="muted">(any of these)</small>${multiPick("data-aud-stage", o.stages, [...stages], "Any stage")}</label></div>
    <small class="muted" data-aud-count></small>
  </fieldset>`;
}
function readAudience(root) {
  const f = root.querySelector("[data-aud]");
  if (!f) return {};
  const mode = f.querySelector("[data-aud-mode]").value;
  const ticked = (name) => [...f.querySelectorAll(`[data-aud-${name}]:checked`)].map((x) => x.value);
  if (mode === "one") return { company_id: Number(f.querySelector("[data-aud-company]").value) || null, target_company_ids: [], target_sectors: [], target_stages: [] };
  if (mode === "companies") return { company_id: null, target_company_ids: ticked("co").map(Number), target_sectors: [], target_stages: [] };
  if (mode === "segment") return { company_id: null, target_company_ids: [], target_sectors: ticked("sector"), target_stages: ticked("stage") };
  return { company_id: null, target_company_ids: [], target_sectors: [], target_stages: [] };
}
function audienceMatches(a) {
  const cos = (audOpts?.companies || []).filter((c) => c.status !== "exited");
  if (a.company_id) return cos.filter((c) => c.id === a.company_id);
  return cos.filter((c) => (!a.target_company_ids.length || a.target_company_ids.includes(c.id))
    && (!a.target_sectors.length || sectorTags(c.sector).some((t) => a.target_sectors.includes(t)))
    && (!a.target_stages.length || a.target_stages.includes(c.stage)));
}
function wireAudience(root) {
  const f = root.querySelector("[data-aud]");
  if (!f) return;
  const update = () => {
    const mode = f.querySelector("[data-aud-mode]").value;
    f.querySelectorAll("[data-aud-show]").forEach((n) => n.classList.toggle("hidden", n.dataset.audShow !== mode));
    const a = readAudience(root);
    const m = audienceMatches(a);
    const empty = (mode === "companies" && !a.target_company_ids.length) || (mode === "segment" && !a.target_sectors.length && !a.target_stages.length);
    f.querySelector("[data-aud-count]").textContent = empty ? "Tick at least one option." :
      `Reaches ${m.length} active compan${m.length === 1 ? "y" : "ies"}${m.length && m.length <= 6 ? ": " + m.map((c) => c.name).join(", ") : ""}.`;
  };
  f.addEventListener("change", update);
  update();
}
function audienceIncomplete(a, root) {
  const mode = root.querySelector("[data-aud-mode]")?.value;
  return (mode === "companies" && !a.target_company_ids.length) || (mode === "segment" && !a.target_sectors.length && !a.target_stages.length);
}

let staffNames = [];
async function loadStaffNames() {
  try { staffNames = await PortalAPI.json("/api/analyst/staff-names"); } catch (_) { staffNames = []; }
}

// A conversation on one founder request: the founder's message, follow-ups and Demo Ventures replies.
async function openThread(workId, box) {
  let d;
  try {
    d = await PortalAPI.json(`/api/analyst/work-items/${workId}/messages`);
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  box.innerHTML = `<div class="thread-list">${d.messages.map((m) => `<div class="msg ${m.from_fund ? "ours" : "theirs"}"><small>${esc(m.author)}${m.from_fund ? " · Demo Ventures" : ""} · ${esc(fmt(m.at))}</small><p>${esc(m.body)}</p></div>`).join("")}</div>
    <form class="thread-form" data-reply-form><label for="reply-${workId}">Reply to the founder (they see it in Demo Ventures support)</label><textarea id="reply-${workId}" name="body" rows="2" required minlength="2" maxlength="4000"></textarea><div class="row-actions"><button class="btn primary" type="submit">Send reply</button></div></form>`;
  box.querySelector("[data-reply-form]").onsubmit = async (e) => {
    e.preventDefault();
    const text = new FormData(e.target).get("body");
    try {
      await PortalAPI.json(`/api/analyst/work-items/${workId}/messages`, { method: "POST", body: JSON.stringify({ body: text }) });
      toast("Reply sent. The founder sees it in Demo Ventures support.");
      await openThread(workId, box);
    } catch (err) {
      toast(err.message);
    }
  };
}

// "Clear sign-in lock" on any account row (after several wrong passwords on one device).
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-unlock]");
  if (!b) return;
  try {
    await PortalAPI.json(`/api/admin/users/${b.dataset.unlock}/unlock`, { method: "POST" });
    toast("Sign-in lock cleared. They can sign in again now.");
  } catch (err) {
    toast(err.message);
  }
});

async function loadQueue() {
  const el = $("tab-queue");
  let items;
  try {
    [items] = await Promise.all([PortalAPI.json("/api/analyst/work-items"), loadStaffNames()]);
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  const open = items.filter((i) => i.internal_status !== "resolved").length;
  $("queueCount").textContent = open || "";
  el.innerHTML = items.length
    ? items.map((item) => `
    <article class="queue-row card">
      <div>
        <small class="muted">${esc(item.public_ref)} · ${esc(item.company_name)} · ${esc(item.founder_name)} · ${esc(fmt(item.created_at))}</small>
        <h3>${esc(item.subject)}</h3>
        <p>${esc(item.context || "")}</p>
        <small class="muted">Topic: ${esc(item.category || "-")}${item.resource_title ? ` · From resource: ${esc(item.resource_title)}` : ""}</small>
        <div class="row-actions" style="margin-top:.5rem"><button class="btn ghost" type="button" data-thread="${item.work_item_id}">Conversation${item.messages ? ` (${item.messages + 1})` : ""}</button>${item.awaiting_reply ? `<span class="pill warn">Founder wrote again</span>` : ""}</div>
        <div class="thread hidden" data-thread-box="${item.work_item_id}"></div>
      </div>
      <div class="queue-controls">
        <span class="status ${item.internal_status === "resolved" ? "resolved" : "progress"}">${STATUS_LABEL[item.internal_status] || esc(item.internal_status)}</span>
        <label for="st-${item.work_item_id}">Status</label>
        <select id="st-${item.work_item_id}" data-status="${item.work_item_id}">
          ${Object.entries(STATUS_LABEL).map(([v, l]) => `<option value="${v}" ${v === item.internal_status ? "selected" : ""}>${l}</option>`).join("")}
        </select>
        <label for="pr-${item.work_item_id}">Priority</label>
        <select id="pr-${item.work_item_id}" data-priority="${item.work_item_id}">
          ${["low", "normal", "high"].map((p) => `<option ${p === item.priority ? "selected" : ""}>${p}</option>`).join("")}
        </select>
        <label for="as-${item.work_item_id}">Owner (shown to founder)</label>
        <select id="as-${item.work_item_id}" data-assign="${item.work_item_id}"><option value="">Demo Ventures team (no named owner)</option>${staffNames.map((n) => `<option${n.name === (item.assigned_to || item.suggested_owner) ? " selected" : ""}>${esc(n.name)}</option>`).join("")}</select>
        <button class="btn primary" data-save="${item.work_item_id}">Update</button>
      </div>
    </article>`).join("")
    : `<p class="empty card">No founder messages yet. They arrive here from Ask Demo Ventures in the founder portal.</p>`;
  el.querySelectorAll("[data-save]").forEach((btn) => {
    btn.onclick = async () => {
      const id = btn.dataset.save;
      btn.disabled = true;
      try {
        await PortalAPI.json(`/api/analyst/work-items/${id}`, {
          method: "PATCH",
          body: JSON.stringify({
            internal_status: el.querySelector(`[data-status="${id}"]`).value,
            priority: el.querySelector(`[data-priority="${id}"]`).value,
            assigned_to: el.querySelector(`[data-assign="${id}"]`).value.trim(),
          }),
        });
        toast("Updated. The founder now sees the new status and owner.");
        await loadQueue();
      } catch (err) {
        toast(err.message);
        btn.disabled = false;
      }
    };
  });
  el.querySelectorAll("[data-thread]").forEach((b) => {
    b.onclick = () => {
      const box = el.querySelector(`[data-thread-box="${b.dataset.thread}"]`);
      if (!box.classList.toggle("hidden")) openThread(b.dataset.thread, box);
    };
  });
}

/* ---------------- Content review */
async function loadContent() {
  const el = $("tab-content");
  let data;
  try {
    data = await PortalAPI.json(`/api/analyst/resources${contentFilter ? `?status=${contentFilter}` : ""}`);
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  const c = data.counts || {};
  $("reviewCount").textContent = c.in_review || "";
  const next = new Date(data.next_review + "T00:00:00").toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short" });
  el.innerHTML = `
    <p class="tab-tools"><button class="btn ghost" type="button" data-guide>Content checklist</button></p>
    <div class="filters section">
      ${[["in_review", "Waiting for approval"], ["approved", "Approved"], ["rejected", "Returned"], ["archived", "Withdrawn"], ["", "All"]].map(([v, l]) => `<button class="chip ${v === contentFilter ? "active" : ""}" data-cfilter="${v}">${l}${v && c[v] ? ` · ${c[v]}` : ""}</button>`).join("")}
      ${can("content.submit") ? `<button class="btn primary" data-upload style="margin-left:auto">+ Submit resource</button><button class="btn ghost" data-bulk-res>Bulk upload (CSV or Excel)</button>` : ""}
    </div>
    <div id="uploadPanel" class="card hidden" style="margin-bottom:1rem"></div>
    <div id="resourceBulk" class="card hidden" style="margin-bottom:1rem"></div>
    ${data.items.length ? data.items.map(resourceRow).join("") : `<p class="empty card">Nothing here.</p>`}`;
  el.querySelectorAll("[data-cfilter]").forEach((b) => (b.onclick = () => { contentFilter = b.dataset.cfilter; loadContent(); }));
  if (el.querySelector("[data-upload]")) el.querySelector("[data-upload]").onclick = showUpload;
  if (el.querySelector("[data-bulk-res]")) el.querySelector("[data-bulk-res]").onclick = () => bulkPanel($("resourceBulk"), { title: "Upload many resources from a CSV", noun: "resource", template: "/api/analyst/resources/bulk-template", endpoint: "/api/analyst/resources/bulk", sheetField: "sheet", withFiles: true, reload: loadContent });
  el.querySelector("[data-guide]").onclick = (e) => { e.preventDefault(); showGuide(); };
  el.querySelectorAll("[data-preview]").forEach((b) => (b.onclick = async () => {
    try { await PortalAPI.download(`/api/analyst/resources/${b.dataset.preview}/download`); } catch (err) { toast(err.message); }
  }));
  el.querySelectorAll("[data-review]").forEach((b) => (b.onclick = () => review(b.dataset.id, b.dataset.review, b)));
  el.querySelectorAll("[data-edit-res]").forEach((b) => (b.onclick = () => toggleEdit(b)));
}

const RESOURCE_CATEGORIES = ["Finance and Compliance", "Fundraising and Investor Relations", "Growth & Sales", "Business Operations", "Product & Tech Strategy", "Market Intelligence", "People & Hiring", "Research and Reports"];
const contentById = new Map();

function resourceRow(r) {
  contentById.set(String(r.id), r);
  const actions = {
    in_review: [["approve", "Approve & publish", "primary"], ["reject", "Return for changes", "ghost"]],
    approved: [["archive", "Withdraw", "ghost"]],
    rejected: [["resubmit", "Move back to review", "ghost"]],
    archived: [["resubmit", "Move back to review", "ghost"]],
  }[r.status] || [];
  const allowedActions = actions.filter(([a]) => can("content.approve") || (a === "resubmit" && can("content.submit")));
  return `<article class="card queue-row">
    <div>
      <small class="muted">${esc(r.category)}${r.subcategory ? " · " + esc(r.subcategory) : ""} · ${esc(r.resource_type)} · ${esc(r.visibility)}${r.placement === "playbook" ? " · shown in the Playbook, not the Resource Library" : ""}</small>
      <h3>${esc(r.title)}</h3>
      <p>${esc(r.description || "")}</p>
      <small class="muted">Owner: ${esc(r.content_owner || "-")} · Submitted by: ${esc(r.submitted_by || "-")}${r.source_url ? ` · Source: <a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">${esc(r.source_url)}</a>` : ""}</small>
      ${r.reviewed_by ? `<br><small class="muted">Last review: ${esc(r.reviewed_by)} · ${esc(fmt(r.reviewed_at))}${r.review_comment ? `: “${esc(r.review_comment)}”` : ""}</small>` : ""}
    </div>
    <div class="queue-controls">
      <span class="status ${RES_CLASS[r.status] || "upcoming"}">${RES_LABEL[r.status] || esc(r.status)}</span>${r.edit_waiting ? `<span class="pill warn">Edit waiting for approval${r.edit_by ? ` · ${esc(r.edit_by)}` : ""}</span>` : ""}
      <small class="muted">${r.downloads} founder download${r.downloads === 1 ? "" : "s"}</small>
      ${r.has_file ? `<button class="btn ghost" data-preview="${r.id}">Preview file</button>` : `<small class="muted">No file attached</small>`}
      <div class="review-actions">${allowedActions.map(([a, l, k]) => `<button class="btn ${k}" data-review="${a}" data-id="${r.id}">${l}</button>`).join("")}${can("content.submit", "content.approve") ? `<button class="btn ghost" data-edit-res="${r.id}" aria-expanded="false">Edit</button>` : ""}</div>
    </div>
    <div class="edit-panel hidden" data-edit-box="${r.id}"></div>
  </article>`;
}


/* Edit a resource's details or replace its file. An Admin's or Analyst's change to a published resource
   waits in Approvals while the current version stays live (the server enforces this). */
async function toggleEdit(btn) {
  const box = document.querySelector(`[data-edit-box="${btn.dataset.editRes}"]`);
  const open = box.classList.toggle("hidden") === false;
  btn.setAttribute("aria-expanded", String(open));
  if (!open) return;
  try { await loadAudienceOptions(); } catch (_) { /* picker falls back to "all companies" */ }
  const r = contentById.get(btn.dataset.editRes);
  const backToReview = r.status === "approved" && !can("content.approve");
  box.innerHTML = `<form class="review-form" data-edit-form="${r.id}">
      <label class="full">Title<input name="title" required minlength="3" maxlength="160" value="${esc(r.title)}"></label>
      <label>Category<select name="category">${RESOURCE_CATEGORIES.map((c) => `<option${c === r.category ? " selected" : ""}>${c}</option>`).join("")}</select></label>
      <label class="full">Description<textarea name="description" required minlength="10" maxlength="600" rows="3">${esc(r.description || "")}</textarea></label>
      <label>Content owner<input name="content_owner" maxlength="80" value="${esc(r.content_owner || "")}"></label>
      <label>Source URL<input name="source_url" type="url" maxlength="500" value="${esc(r.source_url || "")}" placeholder="https://"></label>
      <label>Tags${helpTip("Pick the standard tags that describe the resource. Founders filter and search by them.")}${multiPick('name="tag"', tagOptions(r.tags || []), r.tags || [], "Choose tags")}</label>
      <label>Replace file (optional)<input name="file" type="file" accept=".pdf,.docx,.xlsx,.pptx,.csv"></label>
      ${audiencePicker(r, "Which founders see it")}
      ${backToReview ? `<p class="full notice" style="margin:0">This resource is published. Your changes wait for the Super Admin's approval; founders keep seeing the current version until then.</p>` : ""}
      <div class="full review-actions"><button class="btn primary" type="submit">Save changes</button><button class="btn ghost" type="button" data-edit-cancel>Cancel</button></div>
    </form>`;
  const f = box.querySelector("form");
  wireAudience(f);
  f.querySelector("[data-edit-cancel]").onclick = () => toggleEdit(btn);
  f.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(f);
    const save = f.querySelector('[type="submit"]');
    save.disabled = true;
    try {
      await PortalAPI.json(`/api/analyst/resources/${r.id}/details`, {
        method: "PATCH",
        body: JSON.stringify({
          title: fd.get("title"), category: fd.get("category"),
          description: fd.get("description"), content_owner: fd.get("content_owner"), source_url: fd.get("source_url"),
          tags: fd.getAll("tag"),
          audience: readAudience(f),
        }),
      });
      const file = fd.get("file");
      if (file && file.size) {
        const up = new FormData();
        up.append("file", file);
        await PortalAPI.request(`/api/analyst/resources/${r.id}/file`, { method: "POST", body: up });
      }
      toast(backToReview ? "Saved. Founders keep the current version until the Super Admin approves your changes." : "Saved");
      await loadContent();
    } catch (err) {
      toast(err.message);
      save.disabled = false;
    }
  };
}

async function review(id, action, anchor) {
  let comment = null;
  if (action === "reject") {
    comment = await askInline(anchor, { label: "What should the content owner change?", required: true, multiline: true, save: "Return with this note" });
    if (!comment) return;
  } else if (action === "archive" && !confirm("Withdraw this resource from founders?")) {
    return;
  }
  try {
    await PortalAPI.json(`/api/analyst/resources/${id}`, { method: "PATCH", body: JSON.stringify({ action, comment }) });
    toast({ approve: "Approved, now visible to founders", reject: "Returned to the content owner", archive: "Withdrawn from the library", resubmit: "Moved back to review" }[action]);
    await loadContent();
  } catch (err) {
    toast(err.message);
  }
}

async function showUpload() {
  const p = $("uploadPanel");
  $("resourceBulk")?.classList.add("hidden"); // one panel at a time
  p.classList.toggle("hidden");
  if (p.classList.contains("hidden")) return;
  p.scrollIntoView({ behavior: "smooth", block: "start" });
  try { await loadAudienceOptions(); } catch (_) { /* the picker falls back to "all companies" */ }
  p.innerHTML = `<h2 style="margin-top:0">Submit a resource for review</h2>
    <form id="uploadForm" class="review-form">
      <label>Title${helpTip("The name founders see in the Resource Library.")}<input name="title" required minlength="3" maxlength="160"></label>
      <label>Category${helpTip("The library section it goes in.")}<select name="category">${RESOURCE_CATEGORIES.map((c) => `<option>${c}</option>`).join("")}</select></label>
      <label>Content owner${helpTip("The Demo Ventures person who keeps this resource up to date.")}<input name="content_owner" maxlength="80" placeholder="e.g. Ronit"></label>
      <label>Tags${helpTip("Pick the standard tags that describe the resource. Founders filter and search by them.")}${multiPick('name="tag"', tagOptions(), [], "Choose tags")}</label>
      <label class="full">Description${helpTip("What it is and who it helps, in one or two lines.")}<textarea name="description" required minlength="10" maxlength="600" rows="3"></textarea></label>
      <label class="full">Source URL${helpTip("Required for anything Demo Ventures did not write, so founders can see where it came from.")}<input name="source_url" type="url" maxlength="500" placeholder="https://"></label>
      <label class="full">File (PDF, DOCX, XLSX, PPTX or CSV · max 15 MB)<input name="file" type="file" required accept=".pdf,.docx,.xlsx,.pptx,.csv"></label>
      ${audiencePicker({}, "Which founders see it")}
      <div class="full review-actions"><button class="btn primary" type="submit">Submit for review</button><button class="btn ghost" type="button" data-cancel>Cancel</button></div>
    </form>`;
  p.querySelector("[data-cancel]").onclick = () => p.classList.add("hidden");
  wireAudience(p);
  $("uploadForm").onsubmit = async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector('[type="submit"]');
    const aud = readAudience(e.target);
    if (audienceIncomplete(aud, e.target)) { toast("Choose who the resource is for"); return; }
    btn.disabled = true;
    try {
      const fd = new FormData(e.target);
      fd.set("tags", fd.getAll("tag").join(","));
      fd.delete("tag");
      fd.append("audience", JSON.stringify(aud));
      const res = await PortalAPI.json("/api/analyst/resources", { method: "POST", body: fd });
      toast(`Submitted, queued for the ${res.next_review} review`);
      contentFilter = "in_review";
      await loadContent();
    } catch (err) {
      toast(err.message);
      btn.disabled = false;
    }
  };
}

function showGuide() {
  const p = $("uploadPanel");
  p.classList.remove("hidden");
  p.innerHTML = `<h2 style="margin-top:0">Content checklist, approve only if every answer is yes</h2>
    <ol>
      <li><strong>Useful:</strong> would an early-stage founder use this in the next 90 days?</li>
      <li><strong>Generic and safe:</strong> no company-confidential data, no personal data, no fake names.</li>
      <li><strong>Rights:</strong> our own material, or a source URL with confirmed redistribution / linking rights and attribution.</li>
      <li><strong>Reliable source:</strong> official (government, regulator, industry body) or a reviewed expert source; date checked.</li>
      <li><strong>Not advice:</strong> legal, tax, investment or valuation content is framed as guidance, with the disclaimer.</li>
      <li><strong>Works:</strong> the file opens, formulas calculate, links resolve, and the title/description match the content.</li>
    </ol>
    <button class="btn ghost" type="button" data-guide-close>Close</button>`;
  p.querySelector("[data-guide-close]").onclick = () => p.classList.add("hidden");
}

/* ---------------- Intakes */
const Q_LABEL = { stage: "Stage", business_model: "Sells", team_size: "Team size", priorities: "90-day priorities", fundraising: "Fundraising", tools: "Tools in use", blocker: "Blocker" };
async function loadIntakes() {
  const el = $("tab-intakes");
  let rows;
  try {
    rows = await PortalAPI.json("/api/analyst/intakes");
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  el.innerHTML = rows.length
    ? rows.map((r) => `<article class="card" style="margin-bottom:.9rem"><small class="muted">${esc(fmt(r.created_at))}</small><h3 style="margin:.3rem 0">${esc(r.company_name)} · ${esc(r.founder_name)}</h3><dl class="answers">${Object.entries(Q_LABEL).filter(([k]) => r.answers[k] != null && r.answers[k] !== "" && !(Array.isArray(r.answers[k]) && !r.answers[k].length) || ["priorities", "fundraising"].includes(k)).map(([k, l]) => { const v = r.answers[k]; return `<dt>${l}</dt><dd>${esc(Array.isArray(v) ? v.join(", ") : v || "-")}</dd>`; }).join("")}</dl></article>`).join("")
    : `<p class="empty card">No founder has completed the intake yet. Founders find it at the top of the Resource Library.</p>`;
}

/* ---------------- Admin (admin role only) */
let me = null;
const ROLE_LABEL = { relationship_partner: "Relationship manager", portfolio_analyst: "Portfolio analyst" };
const PHASES = ["Foundation · Days 1–30", "Operations · Days 31–60", "Growth · Days 61–80", "Fundraise readiness · Days 81–100", "Completed"];

function showSecret(title, email, password) {
  const p = $("secretPanel");
  p.innerHTML = `<strong>${esc(title)}</strong><div>One-time password for <strong>${esc(email)}</strong>: <code id="secretValue">${esc(password)}</code> <button class="btn ghost" type="button" id="copySecret">Copy</button></div><small>Share it privately, not in group chats. It is shown only once; the person changes it with the ⚙ button after signing in.</small><div><button class="btn ghost" type="button" id="hideSecret">Done, hide password</button></div>`;
  p.classList.remove("hidden");
  $("copySecret").onclick = async () => {
    try {
      await navigator.clipboard.writeText(password);
      toast("Copied");
    } catch (_) {
      const r = document.createRange();
      r.selectNodeContents($("secretValue"));
      const sel = getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
      toast("Selected: press Ctrl+C");
    }
  };
  $("hideSecret").onclick = () => {
    p.classList.add("hidden");
    p.innerHTML = "";
  };
  p.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* A sign-in link for a founder (invite or reset): shown once, with copy, WhatsApp and email-app buttons, and
   whether the email went out (test mode keeps it in the outbox as "not sent"). */
const EMAIL_STATUS = { sent: "Email sent", queued: "Email queued", failed: "Email failed", not_sent: "Not emailed (test mode)" };
function showLink(title, who, r) {
  const p = $("secretPanel");
  const url = r.invite_link || r.reset_link;
  const st = r.email_status;
  const emailLine = r.outbox_id
    ? `<span class="pill ${st?.status === "sent" ? "on" : st?.status === "failed" ? "off" : "warn"}">${esc(EMAIL_STATUS[st?.status] || "Email queued")}</span>${st?.status !== "sent" && st?.error ? ` <small class="muted">${esc(st.error)}</small>` : ""}`
    : `<span class="pill warn">Not emailed (you chose not to)</span>`;
  p.innerHTML = `<strong>${esc(title)}</strong>
    <div>Personal sign-in link for <strong>${esc(who)}</strong> (works once): <code id="secretValue" style="word-break:break-all">${esc(url)}</code></div>
    <div class="row-actions" style="margin-top:.4rem">${emailLine}
      <button class="btn ghost" type="button" id="copySecret">Copy link</button>
      <a class="btn ghost" href="${esc(r.whatsapp_url)}" target="_blank" rel="noopener noreferrer">Send on WhatsApp</a>
      <a class="btn ghost" href="${esc(r.mailto_url)}">Open in email app</a>
      <button class="btn ghost" type="button" id="hideSecret">Done</button></div>
    <small>Share it only with this person. They choose their own password with it; nobody else ever sees it. Every message is also in Messages → Sent emails.</small>`;
  p.classList.remove("hidden");
  $("copySecret").onclick = async () => {
    try { await navigator.clipboard.writeText(url); toast("Link copied"); } catch (_) {
      const range = document.createRange(); range.selectNodeContents($("secretValue"));
      const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range); toast("Selected: press Ctrl+C");
    }
  };
  $("hideSecret").onclick = () => { p.classList.add("hidden"); p.innerHTML = ""; };
  p.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function submitJSON(e, path, method, build, okMsg, reload) {
  e.preventDefault();
  const btn = e.target.querySelector('[type="submit"]');
  btn.disabled = true;
  try {
    await PortalAPI.json(path, { method, body: JSON.stringify(build(new FormData(e.target))) });
    toast(okMsg);
    await reload();
  } catch (err) {
    toast(err.message);
    btn.disabled = false;
  }
}

async function userAction(id, action, email, reload) {
  const body = { reset: { reset_password: true }, deactivate: { active: false }, activate: { active: true } }[action];
  if (action === "deactivate" && !confirm(`Deactivate ${email}? They are signed out at once and cannot sign in until reactivated.`)) return;
  if (action === "reset" && !confirm(`Reset the password for ${email}? Their current password stops working at once.`)) return;
  try {
    const r = await PortalAPI.json(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(body) });
    await reload();
    if (r.reset_link) showLink("Password reset", email, r);
    else if (r.temporary_password) showSecret("Password reset", email, r.temporary_password);
    else toast(action === "deactivate" ? "Account deactivated and signed out" : "Account reactivated");
  } catch (err) {
    toast(err.message);
  }
}

/* ---------------- Shared wording (one set of terms across the portal) */
const ROLE_NAMES = { super_admin: "Super Admin", admin: "Admin", analyst: "Analyst" };
const ASSIGNMENT_LABEL = { relationship_partner: "Relationship manager", portfolio_analyst: "Portfolio analyst" };
const APPROVAL_LABEL = { pending: "Waiting for approval", approved: "Approved", returned: "Returned for changes" };
const APPROVAL_CLASS = { pending: "warn", approved: "on", returned: "off" };
const approvalPill = (a) => (a && a !== "approved" ? ` <span class="pill ${APPROVAL_CLASS[a] || ""}">${esc(APPROVAL_LABEL[a] || a)}</span>` : "");
const afterAdd = (approval, live) => (approval === "pending" ? "Saved. It waits for the Super Admin's approval before founders see it." : live);

/* ---------------- Overview */
async function loadOverview() {
  const el = $("tab-overview");
  let d;
  try {
    d = await PortalAPI.json("/api/admin/overview");
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  const c = d.counts;
  const stat = (n, l, tab) => `<div class="card stat${tab ? " stat-link" : ""}"${tab ? ` data-goto-tab="${tab}" role="button" tabindex="0"` : ""}><strong>${esc(n)}</strong><span>${esc(l)}</span></div>`;
  el.innerHTML = `
    <div class="stat-grid">
      ${can("content.approve") ? stat(c.awaiting_approval, "Waiting for your approval", "approvals") : stat(c.content_in_review, "Resources waiting for approval")}
      ${stat(c.open_requests, "Open founder requests", can("requests.handle") ? "queue" : "")}
      ${stat(c.companies, "Portfolio companies")}${stat(c.active_founders, "Active founder accounts")}
      ${stat(c.approved_resources, "Approved resources")}${stat(c.downloads_30d, "Downloads, last 30 days")}
      ${stat(c.intakes_completed + " / " + c.companies, "Companies with questionnaire done")}${can("staff.manage") || can("admins.manage") ? stat(c.team_members, "Demo Ventures team accounts") : ""}
    </div>
    <div class="card overview-companies"><h3 style="margin-top:0">${me.assigned_only?.includes("companies.view") ? "Your companies" : "Portfolio companies"}</h3><div class="scroll"><table class="data one-line"><thead><tr><th>Company</th><th class="num">Founders</th><th class="num">Open requests</th><th class="num">Downloads</th><th>Questionnaire</th><th>Last founder sign-in</th></tr></thead><tbody>
        ${d.companies.map((r) => `<tr><td><strong>${esc(r.company)}</strong></td><td class="num">${r.founders}</td><td class="num">${r.open_requests}</td><td class="num">${r.downloads}</td><td>${r.intake_done ? "Done" : "Not yet"}</td><td>${esc(fmt(r.last_sign_in))}</td></tr>`).join("") || `<tr><td colspan="6" class="muted">No companies assigned to you yet.</td></tr>`}
      </tbody></table></div></div>
    <div class="two-col" style="margin-top:1rem">
      <div class="card"><h3 style="margin-top:0">Most downloaded</h3>${d.top_resources.length ? `<table class="data"><tbody>${d.top_resources.map((r) => `<tr><td>${esc(r.title)}<br><small class="muted">${esc(r.category)}</small></td><td class="num">${r.downloads}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">No downloads yet.</p>`}</div>
    </div>
    ${can("audit.view") ? `<div class="card" style="margin-top:1rem"><h3 style="margin-top:0">Latest in the audit trail</h3>${d.recent_admin_actions.length ? d.recent_admin_actions.map(auditRow).join("") : `<p class="muted">Nothing yet. Every change and download is recorded.</p>`}</div>` : ""}`;
  el.querySelectorAll("[data-goto-tab]").forEach((s) => {
    s.onclick = () => switchTab(s.dataset.gotoTab);
    s.onkeydown = (e) => { if (e.key === "Enter") switchTab(s.dataset.gotoTab); };
  });
}

/* ---------------- Approvals (Super Admin): everything staff added, in one list */
async function loadApprovals() {
  const el = $("tab-approvals");
  let d;
  try {
    d = await PortalAPI.json("/api/admin/approvals");
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  $("approvalCount").textContent = d.items.length || "";
  el.innerHTML = `
    
    ${d.items.length ? d.items.map((i) => `<article class="card approval-row" data-approval="${i.kind}:${i.id}">
      <div><span class="pill">${esc(i.kind_label)}</span>
        <h3>${esc(i.title)}</h3>
        <small class="muted">${esc(i.detail || "")}${i.company ? ` · ${esc(i.company)}` : ""} · added by ${esc(i.submitted_by || "-")} · ${esc(fmt(i.submitted_at))}</small>
        ${i.kind === "event" && i.extra ? `<br><small class="muted">Join: ${esc(i.extra)}</small>` : ""}${i.kind === "event_link" ? `<br><small class="muted">New join link: <strong>${esc(i.extra)}</strong>. ${esc(i.body || "")}. Founders keep seeing the event; the link replaces the current one once approved.</small>` : ""}${i.kind === "event_recording" ? `<br><small class="muted">New recording link: <strong>${esc(i.extra)}</strong></small>` : ""}
        ${i.body && !["event_link"].includes(i.kind) ? `<p class="approval-body">${esc(i.body)}</p>` : ""}${i.link && /^https?:\/\//.test(i.link) ? `<small><a href="${esc(i.link)}" target="_blank" rel="noopener noreferrer">Open the source link ↗</a></small>` : ""}</div>
      <div class="review-actions">
        ${i.kind === "resource" ? `<button class="btn ghost" type="button" data-open-res>Preview file</button>` : ""}
        <button class="btn primary" type="button" data-decide="approve">Approve</button>
        <button class="btn ghost" type="button" data-decide="return">Return for changes</button>
      </div></article>`).join("") : `<p class="empty card">Nothing is waiting for approval.</p>`}`;
  el.querySelectorAll("[data-approval]").forEach((row) => {
    const [kind, id] = row.dataset.approval.split(":");
    const open = row.querySelector("[data-open-res]");
    if (open) open.onclick = async () => { try { await PortalAPI.download(`/api/analyst/resources/${id}/download`); } catch (err) { toast(err.message); } };
    row.querySelectorAll("[data-decide]").forEach((b) => {
      b.onclick = async () => {
        const action = b.dataset.decide;
        let comment = null;
        if (action === "return") {
          comment = await askInline(b, { label: "What should change? The person who added it sees this note.", required: true, multiline: true, save: "Return with this note" });
          if (!comment) return;
        }
        try {
          if (kind === "resource") {
            await PortalAPI.json(`/api/analyst/resources/${id}`, { method: "PATCH", body: JSON.stringify({ action: action === "approve" ? "approve" : "reject", comment }) });
          } else {
            await PortalAPI.json(`/api/admin/approvals/${kind}/${id}`, { method: "POST", body: JSON.stringify({ action, comment }) });
          }
          toast(action === "approve" ? "Approved: founders can see it now" : "Returned with your note");
          await loadApprovals();
        } catch (err) {
          toast(err.message);
        }
      };
    });
  });
}

/* ---------------- Companies & founders */
function previewCompany(company) {
  // A read-only view of this company's founder portal, in its own tab so the workspace stays open.
  const url = `/?preview=${encodeURIComponent(company.id)}&company=${encodeURIComponent(company.name)}`;
  const tab = window.open(url, "_blank");
  if (!tab) window.location.href = url; // pop-ups blocked: open it here instead
}

// A choice of active staff accounts in the given tiers, so an assignment always links to a real person.
function staffPicker(id, name, current, tiers) {
  const people = staffNames.filter((m) => tiers.includes(m.tier));
  const known = people.some((m) => m.name === current);
  return `<select id="${id}" name="${name}"><option value="">Choose…</option>${current && !known ? `<option selected>${esc(current)}</option>` : ""}${people.map((m) => `<option${m.name === current ? " selected" : ""}>${esc(m.name)}</option>`).join("")}</select>`;
}

function companyCard(c) {
  const t = c.team || {};
  const pb = c.playbook || { progress_pct: 0, current_phase: PHASES[0], owner_name: "" };
  const can_ = c.can || {};
  const founders = c.founders.map((f) => `<div class="person"><span>${esc(f.full_name)}${f.title ? ` <small style="display:inline">· ${esc(f.title)}</small>` : ""}<small>${esc(f.email)}${f.phone ? ` · ${esc(f.phone)}` : ""} · last sign-in ${esc(fmt(f.last_sign_in))}</small></span><span class="row-actions"><span class="pill ${f.active ? "on" : "off"}">${f.active ? "Active" : "Inactive"}</span>${can_.founders ? `<button class="btn ghost" type="button" data-user-action="reset" data-id="${f.id}" data-email="${esc(f.email)}">Reset password</button><button class="btn ghost" type="button" data-unlock="${f.id}">Clear sign-in lock</button><button class="btn ghost" type="button" data-user-action="${f.active ? "deactivate" : "activate"}" data-id="${f.id}" data-email="${esc(f.email)}">${f.active ? "Deactivate" : "Reactivate"}</button><button class="btn ghost" type="button" data-contact="${f.id}" data-name="${esc(f.full_name)}" data-email="${esc(f.email)}" data-title="${esc(f.title || "")}" data-phone="${esc(f.phone || "")}">Edit details</button>` : ""}</span></div>`).join("");
  // Each company is a dropdown: the name and key facts show closed; everything else opens on click.
  return `<details class="card company co-dropdown" id="co-${c.id}" data-co-card="${c.id}"${coOpen.has(String(c.id)) ? " open" : ""}>
    <summary class="co-summary">${/^data:image\/(png|jpeg|webp);base64,/.test(c.logo || "") ? `<img class="co-logo" src="${c.logo}" alt="">` : `<span class="co-logo co-logo-empty" aria-hidden="true">${esc(c.name.replace(/\[.*?\]\s*/, "").slice(0, 1).toUpperCase())}</span>`}<span class="co-title"><strong>${esc(c.name)}</strong>${c.status === "exited" ? ` <span class="pill off">Exited</span>` : ""}${c.legal_name ? `<small class="muted co-legal">${esc(c.legal_name)}</small>` : ""}<small class="muted">${esc([c.sector || "Sector not set", c.stage, c.city, c.fund, c.invested ? `invested ${c.invested}` : ""].filter(Boolean).join(" · "))}</small></span></summary>
    <div class="company-head"><div>${c.about ? `<p class="muted" style="margin:0;font-size:13px;max-width:70ch">${esc(c.about)}</p>` : ""}</div>
      <div class="row-actions"><small class="muted">Added ${esc(fmt(c.created_at))}</small><button class="btn primary" type="button" data-co-profile="${c.id}" aria-expanded="false">Company profile</button>${c.can?.edit ? `<button class="btn ghost" type="button" data-co-edit="${c.id}">Edit details</button><label class="btn ghost co-logo-btn">${c.logo ? "Change logo" : "Add logo"}<input type="file" accept="image/png,image/jpeg,image/webp" data-co-logo="${c.id}" hidden></label>${c.logo ? `<button class="btn ghost" type="button" data-co-logo-remove="${c.id}">Remove logo</button>` : ""}` : ""}${c.website ? `<a class="btn ghost" href="${/^https?:\/\//i.test(c.website) ? esc(c.website) : "#"}" target="_blank" rel="noopener noreferrer">Website ↗</a>` : ""}${can("companies.add") && !me.assigned_only?.includes("companies.add") ? `<button class="btn ghost" type="button" data-co-status="${c.id}" data-to="${c.status === "exited" ? "active" : "exited"}" data-name="${esc(c.name)}">${c.status === "exited" ? "Mark as active" : "Mark as exited"}</button>` : ""}${can("founder.preview") ? `<button class="btn ghost" type="button" data-preview-co="${c.id}" data-preview-name="${esc(c.name)}">Preview founder portal</button>` : ""}</div></div>
    <div class="hidden co-profile" data-profile-box="${c.id}"></div>
    <div class="sub-grid">
      <div><h4>Founders (${c.founders.length})</h4>
        ${founders || `<p class="muted">No founders yet.</p>`}
        ${can_.founders ? `<details class="invite-more"><summary class="btn ghost">+ Invite ${c.founders.length ? "another" : "a"} founder</summary><form class="inline-form" data-founder-form="${c.id}"><input id="fn-${c.id}" name="full_name" required minlength="2" maxlength="120" placeholder="Founder's full name" aria-label="Founder's full name"><input id="fe-${c.id}" name="email" type="email" required placeholder="founder@example.com" aria-label="Founder email"><input id="ft-${c.id}" name="title" maxlength="80" placeholder="Role, e.g. Co-founder & CEO" aria-label="Founder role"><input id="fp-${c.id}" name="phone" maxlength="30" placeholder="Phone for WhatsApp (optional)" aria-label="Founder phone"><textarea name="note" maxlength="600" rows="2" placeholder="Personal note added to the invite (optional)" aria-label="Personal note"></textarea><label class="check"><input type="checkbox" name="send_email" checked> Email the invite</label><div class="row-actions"><button class="btn ghost" type="button" data-invite-preview="${c.id}">Preview message</button><button class="btn primary" type="submit">Send invite</button></div></form></details>` : ""}
      </div>
      <div><h4>Demo Ventures team</h4>
        ${can_.team ? `<form class="inline-form" data-team-form="${c.id}">
          <label class="muted" style="font-size:12px">Relationship manager (Admin)${staffPicker(`rp-${c.id}`, "relationship_partner", t.relationship_partner?.person, ["admin", "super_admin"])}</label>
          <label class="muted" style="font-size:12px">Portfolio analyst${staffPicker(`pa-${c.id}`, "portfolio_analyst", t.portfolio_analyst?.person, ["analyst", "admin"])}</label>
          <div class="row-actions"><button class="btn primary" type="submit">Save team</button><button class="btn ghost" type="button" data-history="${c.id}">History</button></div>
        </form>` : `<p class="muted" style="margin:.2rem 0">Relationship manager: <strong>${esc(t.relationship_partner?.person || "-")}</strong><br>Portfolio analyst: <strong>${esc(t.portfolio_analyst?.person || "-")}</strong></p><div class="row-actions"><button class="btn ghost" type="button" data-history="${c.id}">History</button></div>`}
        <div class="hidden" data-history-box="${c.id}"></div>
      </div>
      <div><h4>100-Day Playbook · ${pb.progress_pct}%</h4>
        <small class="muted">${pb.tasks_done} of ${pb.tasks_total} tasks done · ${esc(pb.current_phase)}. Progress follows the tasks the founder ticks off.</small>
        ${can_.playbook ? `<form class="inline-form" data-playbook-form="${c.id}">
          <label class="muted" style="font-size:12px">Demo Ventures owner${staffPicker(`po-${c.id}`, "owner_name", pb.owner_name, ["super_admin", "admin", "analyst"])}</label>
          <div class="row-actions"><button class="btn primary" type="submit">Save owner</button><button class="btn ghost" type="button" data-tasks="${c.id}">Manage tasks</button></div>
        </form>` : `<p class="muted" style="margin:.2rem 0">Demo Ventures owner: <strong>${esc(pb.owner_name || "-")}</strong></p>`}
        <div class="hidden" data-tasks-box="${c.id}"></div>
      </div>
    </div>
  </details>`;
}

/* Company profiles (alpha v1.2.6): the gap list, the spreadsheet import and the shared firm list. */
async function loadProfileTools(box) {
  box.innerHTML = `<p class="muted">Loading…</p>`;
  let gaps, firms;
  try {
    [gaps, firms] = await Promise.all([PortalAPI.json("/api/admin/profile-gaps"), PortalAPI.json("/api/admin/firms")]);
  } catch (err) {
    box.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  const canImport = can("companies.add"), canRename = can("content.approve");
  const avg = gaps.length ? Math.round(gaps.reduce((t, g) => t + g.completeness.pct, 0) / gaps.length) : 0;
  const alertCount = gaps.reduce((t, g) => t + g.alerts.length, 0);
  box.innerHTML = `
    <p class="muted" style="margin:.75rem 0">${gaps.length} active companies · profiles ${avg}% complete on average · ${alertCount} certificate${alertCount === 1 ? "" : "s"} expired or expiring soon.</p>
    <div class="table-wrap"><table class="cp-table cp-gaps"><thead><tr><th>Company</th><th class="num">Complete</th><th>Needs attention</th><th>Still to fill in</th></tr></thead><tbody>
      ${gaps.sort((a, b) => a.completeness.pct - b.completeness.pct).map((g) => `<tr><td><button class="btn ghost" type="button" data-gap-open="${g.company_id}">${esc(g.brand_name)}</button>${g.legal_name ? `<br><small class="muted">${esc(g.legal_name)}</small>` : ""}</td>
        <td class="num">${g.completeness.pct}%</td>
        <td>${g.alerts.map((a) => `<span class="cp-badge ${a.level}">${a.level === "red" ? "Expired" : "Soon"}: ${esc(a.item)}</span>`).join("")}${g.confirm_due ? `<span class="cp-badge amber">${g.confirmed_at ? "Confirmation over a year old" : "Never confirmed"}</span>` : ""}</td>
        <td><small class="muted">${esc(g.completeness.missing.slice(0, 6).join(", "))}${g.completeness.missing.length > 6 ? ` and ${g.completeness.missing.length - 6} more` : ""}</small></td></tr>`).join("") || `<tr><td colspan="4" class="muted">No companies.</td></tr>`}
    </tbody></table></div>
    ${canImport ? `<h4>Import from a spreadsheet</h4>
    <p class="muted" style="font-size:13px">Upload the existing company sheet as CSV or Excel (.xlsx). Each row is matched to a company by its short ID, brand name or legal name. Empty cells leave the current value alone. Check the file first; the import saves only when every row is valid.</p>
    <form class="inline-form cp-workspace-tools" id="profileImport">
      <select name="kind" aria-label="What the sheet holds"><option value="profile">Profile details (one row per company)</option><option value="credit">Credit lines and cards (one row each)</option></select>
      <input type="file" name="file" accept=".csv,.xlsx" required aria-label="Spreadsheet file">
      <button class="btn ghost" type="button" data-template>Download the template</button>
      <button class="btn ghost" type="submit" data-dry="1">Check the file</button>
      <button class="btn primary" type="submit" data-dry="0">Import</button>
    </form><div data-import-result></div>` : ""}
    <h4>Shared firm list (${firms.firms.length})</h4>
    <p class="muted" style="font-size:13px">Auditors, company secretaries, law firms, banks and lenders are entered once and picked from this list on both sides of the portal. A name typed with different capitals, "&amp;" or a suffix such as LLP or Pvt Ltd joins the firm already listed.${canRename ? " Correct a spelling with Rename." : ""}</p>
    <div class="table-wrap"><table class="cp-table"><thead><tr><th>Firm</th><th>Used as</th><th class="num">Companies</th>${canRename ? "<th></th>" : ""}</tr></thead><tbody>
      ${firms.firms.map((f) => `<tr><td>${esc(f.name)}</td><td><small class="muted">${esc(f.kinds.map((k) => firms.kinds[k] || k).join(", "))}</small></td><td class="num">${f.companies}</td>${canRename ? `<td><button class="btn ghost" type="button" data-firm-rename="${f.id}" data-name="${esc(f.name)}">Rename</button></td>` : ""}</tr>`).join("") || `<tr><td colspan="4" class="muted">No firms yet. They are added as profiles are filled in.</td></tr>`}
    </tbody></table></div>`;
  box.querySelectorAll("[data-gap-open]").forEach((b) => (b.onclick = () => {
    const id = b.dataset.gapOpen;
    const picker = $("coPick");
    if (picker) { picker.value = id; picker.onchange(); }
    const card = $(`co-${id}`);
    if (card) { card.open = true; coOpen.add(id); }
    const btn = card?.querySelector("[data-co-profile]");
    if (btn && btn.getAttribute("aria-expanded") !== "true") btn.click();
    card?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  box.querySelectorAll("[data-firm-rename]").forEach((b) => (b.onclick = async () => {
    const name = await askInline(b, { label: "Correct firm name", value: b.dataset.name, required: true, save: "Rename" });
    if (!name || name === b.dataset.name) return;
    try {
      await PortalAPI.json(`/api/admin/firms/${b.dataset.firmRename}`, { method: "PATCH", body: JSON.stringify({ name }) });
      toast(`Renamed to ${name}`);
      loadProfileTools(box);
    } catch (err) { toast(err.message); }
  }));
  const form = box.querySelector("#profileImport");
  if (!form) return;
  form.querySelector("[data-template]").onclick = async () => {
    try { toast(`Downloaded ${await PortalAPI.download(`/api/admin/profile-import/template?kind=${form.kind.value}`)}`); } catch (err) { toast(err.message); }
  };
  let dry = "1";
  form.querySelectorAll("[type=submit]").forEach((b) => b.addEventListener("click", () => (dry = b.dataset.dry)));
  form.onsubmit = async (e) => {
    e.preventDefault();
    const out = box.querySelector("[data-import-result]");
    if (!form.file.files[0]) { toast("Choose a CSV or .xlsx file first"); return; }
    const fd = new FormData();
    fd.append("file", form.file.files[0]);
    fd.append("kind", form.kind.value);
    fd.append("dry_run", dry === "1" ? "true" : "false");
    form.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      const r = await PortalAPI.json("/api/admin/profile-import", { method: "POST", body: fd });
      const head = r.dry_run
        ? `Check: ${r.ok} of ${r.rows} rows are fine${r.errors ? `, ${r.errors} need fixing` : ". Press Import to save them."}`
        : r.saved ? `Imported ${r.rows} rows.` : `Nothing was saved: ${r.errors} row${r.errors === 1 ? "" : "s"} need fixing first.`;
      out.innerHTML = `<div class="card" style="margin-top:.5rem"><strong>${esc(head)}</strong><ul class="muted" style="font-size:13px">${r.results.map((x) => `<li>Row ${x.row} (${esc(x.brand_name || x.company || "no company")}): ${x.error ? `<span style="color:var(--red)">${esc(x.error)}</span>` : x.changes.length ? esc(x.changes.join(", ")) : "no changes"}</li>`).join("")}</ul></div>`;
      if (r.saved) { toast(head); setTimeout(() => loadProfileTools(box), 1500); }
    } catch (err) {
      out.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    } finally {
      form.querySelectorAll("button").forEach((b) => (b.disabled = false));
    }
  };
}

let coPick = ""; // company chosen in the "Go to a company" picker
const coOpen = new Set(); // companies opened in this tab, kept open when the list reloads
async function loadCompanies() {
  const el = $("tab-companies");
  let rows;
  try {
    rows = await PortalAPI.json("/api/admin/companies");
    await loadStaffNames();
    await loadAudienceOptions(true).catch(() => null);
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  const pick = rows.some((r) => String(r.id) === coPick) ? coPick : "";
  el.innerHTML = `
    ${rows.length > 1 ? `<div class="card co-picker"><label for="coPick">Go to a company</label>
      <select id="coPick"><option value="">All companies (${rows.length})</option>${rows.map((r) => `<option value="${r.id}"${String(r.id) === pick ? " selected" : ""}>${esc(r.name)}${r.status === "exited" ? " (exited)" : ""}</option>`).join("")}</select></div>` : ""}
    
    ${!can("companies.add") ? "" : `<details class="card section" id="newCompany"><summary><strong>+ Add a portfolio company</strong></summary>
      <form class="inline-form" id="companyForm" style="margin-top:.75rem">
        <div class="review-form"><label>Company name${helpTip("The brand name founders and the team use, for example Nimbus Mobility. The legal name goes in the company profile.")}<input id="nc-name" name="name" required minlength="2" maxlength="120"></label>
        <div class="slug-line"><small class="muted">Short ID${helpTip("A web-safe ID made from the name. It never changes, so links and imports keep working.")}: <code id="nc-slug-view">appears as you type the name</code></small><button type="button" class="text-btn" data-slug-edit>Change</button><input id="nc-slug" name="slug" class="hidden" required pattern="[a-z0-9]+(-[a-z0-9]+)*" maxlength="60" aria-label="Short ID"></div>
        <label>Sectors${helpTip("Pick every sector that fits. Sector updates and resources reach founders by these tags.")}${multiPick('name="sector_tag"', audOpts?.sectors || [], [], "Choose sectors")}</label>
        <label>Stage${helpTip("The company's current funding stage.")}<select id="nc-stage" name="stage"><option value="">Not set</option>${(audOpts?.stages || ["Pre-seed", "Seed", "Series A", "Series B", "Series C+"]).map((s) => `<option>${esc(s)}</option>`).join("")}</select></label>
        <label>City<input id="nc-city" name="city" maxlength="80" placeholder="e.g. Bengaluru"></label>
        <label>Demo Ventures funds${helpTip("Every Demo Ventures fund that has invested. Pick more than one if needed.")}${multiPick('name="fund"', FUNDS, [], "Choose funds")}</label>
        <label>Invested${helpTip("When Demo Ventures first invested, for example May 2021.")}<input id="nc-invested" name="invested" maxlength="40" placeholder="e.g. May 2021"></label>
        <label>Website<input id="nc-website" name="website" type="url" maxlength="300" placeholder="https://"></label>
        <label class="full">About the company${helpTip("One or two lines on what the company does. Founders see this on their profile.")}<textarea id="nc-about" name="about" maxlength="600" rows="2" placeholder="What the company does, in one or two lines"></textarea></label>
        <label class="full">Company profile sheet (optional)${helpTip("Have the company's details in a spreadsheet? Add the CSV or Excel file here and the profile fills in when you add the company. Download the template from Company profiles below.")}<input type="file" name="profile_sheet" accept=".csv,.xlsx"></label>
        <h4 class="full" style="margin:.4rem 0 0">First founder (optional): invite them now</h4>
        <label>Founder's full name<input id="nc-fname" name="f_name" maxlength="120"></label>
        <label>Founder's email<input id="nc-femail" name="f_email" type="email"></label>
        <label>Role<input id="nc-ftitle" name="f_title" maxlength="80" placeholder="e.g. Co-founder & CEO"></label>
        <label>Phone for WhatsApp<input id="nc-fphone" name="f_phone" maxlength="30"></label>
        <label class="full check"><input type="checkbox" name="f_send" checked> Email the invite</label></div>
        <div class="row-actions"><button class="btn primary" type="submit">Add company</button></div>
      </form></details>`}
    <datalist id="sectorTags">${(audOpts?.sectors || []).map((t) => `<option value="${esc(t)}">`).join("")}</datalist>
    <details class="card section" id="profileTools"><summary><strong>Company profiles: gaps, spreadsheet import and the shared firm list</strong></summary><div data-profile-tools></div></details>
    ${rows.map(companyCard).join("") || `<p class="empty card">No companies assigned to you yet.</p>`}`;
  // Company picker: show one company instead of scrolling through all of them (kept across reloads of this tab).
  const showPicked = (scroll) => {
    el.querySelectorAll("[data-co-card]").forEach((card) => card.classList.toggle("hidden", !!coPick && card.dataset.coCard !== coPick));
    if (coPick) { coOpen.add(coPick); const card = $(`co-${coPick}`); if (card) card.open = true; }
    if (scroll && coPick) $(`co-${coPick}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  coPick = pick;
  showPicked(false);
  el.querySelectorAll("[data-co-card]").forEach((card) => card.addEventListener("toggle", () => {
    if (card.open) coOpen.add(card.dataset.coCard); else coOpen.delete(card.dataset.coCard);
  }));
  const picker = $("coPick");
  if (picker) picker.onchange = () => { coPick = picker.value; showPicked(true); };
  const nameInput = $("nc-name");
  if (nameInput) {
    const slugInput = $("nc-slug");
    const slugView = $("nc-slug-view");
    nameInput.addEventListener("input", () => {
      if (!slugInput.dataset.touched) slugInput.value = nameInput.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
      slugView.textContent = slugInput.value || "appears as you type the name";
    });
    slugInput.addEventListener("input", () => { slugInput.dataset.touched = "1"; slugView.textContent = slugInput.value; });
    el.querySelector("[data-slug-edit]").onclick = () => { slugInput.classList.toggle("hidden"); slugInput.focus(); };
    $("companyForm").onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const btn = e.target.querySelector('[type="submit"]');
      const fname = String(fd.get("f_name") || "").trim(), femail = String(fd.get("f_email") || "").trim();
      if ((fname && !femail) || (!fname && femail)) { toast("Give the founder's name and email, or leave both empty"); return; }
      btn.disabled = true;
      try {
        if (!fd.get("slug")) { toast("Type the company name first"); btn.disabled = false; return; }
        const r = await PortalAPI.json("/api/admin/companies", { method: "POST", body: JSON.stringify({
          name: fd.get("name"), slug: fd.get("slug"), sector: fd.getAll("sector_tag").join(", ") || null, stage: fd.get("stage") || null,
          city: fd.get("city") || null, fund: fd.getAll("fund").join(", ") || null, invested: fd.get("invested") || null, website: fd.get("website") || null, about: fd.get("about") || null,
          founder: fname ? { full_name: fname, email: femail, title: fd.get("f_title") || null, phone: fd.get("f_phone") || null, send_email: fd.get("f_send") === "on" } : null }) });
        // The profile sheet, if one was added, fills the new company's profile straight away.
        let sheetNote = "";
        const sheet = fd.get("profile_sheet");
        if (sheet && sheet.size) {
          const up = new FormData();
          up.append("file", sheet);
          up.append("kind", "profile");
          up.append("dry_run", "false");
          up.append("company_id", String(r.id));
          try {
            const res = await PortalAPI.json("/api/admin/profile-import", { method: "POST", body: up });
            sheetNote = res.saved ? " Its profile was filled in from the sheet." : ` The sheet was not imported: ${res.results.find((x) => x.error)?.error || "check the file"}.`;
          } catch (err) {
            sheetNote = ` The sheet was not imported: ${err.message}.`;
          }
        }
        await loadAudienceOptions(true);
        coPick = String(r.id);
        await loadCompanies();
        if (r.invite) showLink(`${fd.get("name")} added and its founder invited.${sheetNote}`, r.invite.email, r.invite);
        else toast(`Company added.${sheetNote} Now invite its founders.`);
      } catch (err) {
        toast(err.message);
        btn.disabled = false;
      }
    };
  }
  el.querySelectorAll("[data-co-logo]").forEach((inp) => {
    inp.onchange = async () => {
      const file = inp.files[0];
      if (!file) return;
      if (file.size > 300 * 1024) { toast("The logo must be 300 KB or smaller"); inp.value = ""; return; }
      const fd = new FormData();
      fd.append("file", file);
      try {
        const resp = await PortalAPI.request(`/api/admin/companies/${inp.dataset.coLogo}/logo`, { method: "POST", body: fd });
        if (!resp.ok) { const j = await resp.json().catch(() => ({})); throw new Error(j.detail || "Could not save the logo"); }
        toast("Logo saved");
        await loadCompanies();
      } catch (err) {
        toast(err.message);
      }
      inp.value = "";
    };
  });
  el.querySelectorAll("[data-co-logo-remove]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Remove this company's logo?")) return;
      try {
        await PortalAPI.json(`/api/admin/companies/${b.dataset.coLogoRemove}/logo`, { method: "DELETE" });
        toast("Logo removed");
        await loadCompanies();
      } catch (err) {
        toast(err.message);
      }
    };
  });
  el.querySelectorAll("[data-co-edit]").forEach((b) => {
    b.onclick = () => {
      const c = rows.find((x) => x.id == b.dataset.coEdit);
      const stages = [...(audOpts?.stages || ["Pre-seed", "Seed", "Series A", "Series B", "Series C+"])];
      if (c.stage && !stages.includes(c.stage)) stages.push(c.stage);
      editForm(b, `Edit details: ${c.name}`, `
        <label>Company name<input name="name" required minlength="2" maxlength="120" value="${esc(c.name)}"></label>
        <label>Sectors${multiPick('name="sector_tag"', [...new Set([...(audOpts?.sectors || []), ...sectorTags(c.sector)])], sectorTags(c.sector), "Choose sectors")}</label>
        <label>Stage<select name="stage"><option value="">Not set</option>${stages.map((s) => `<option${s === c.stage ? " selected" : ""}>${esc(s)}</option>`).join("")}</select></label>
        <label>City<input name="city" maxlength="80" value="${esc(c.city || "")}"></label>
        <label>Demo Ventures funds${multiPick('name="fund"', [...new Set([...FUNDS, ...sectorTags(c.fund)])], sectorTags(c.fund), "Choose funds")}</label>
        <label>Invested<input name="invested" maxlength="40" value="${esc(c.invested || "")}"></label>
        <label class="full">Website<input name="website" type="url" maxlength="300" placeholder="https://" value="${esc(c.website || "")}"></label>
        <label class="full">About the company<textarea name="about" maxlength="600" rows="2">${esc(c.about || "")}</textarea></label>
        <small class="full muted">The short ID (${esc(c.slug)}) stays the same. Clear a field to remove it.</small>`,
        "Save details", async (fd) => {
          const body = {};
          for (const k of ["name", "sector", "stage", "city", "fund", "invested", "website", "about"]) {
            const v = k === "sector" ? fd.getAll("sector_tag").join(", ") : k === "fund" ? fd.getAll("fund").join(", ") : String(fd.get(k) || "").trim();
            if (v !== String(c[k] || "")) body[k] = v;
          }
          if (!Object.keys(body).length) { toast("Nothing changed"); return true; }
          try {
            await PortalAPI.json(`/api/admin/companies/${c.id}`, { method: "PATCH", body: JSON.stringify(body) });
            toast(`${body.name || c.name}: details saved`);
            await loadCompanies();
            return true;
          } catch (err) {
            toast(err.message);
            return false;
          }
        });
    };
  });
  el.querySelectorAll("[data-preview-co]").forEach((b) => (b.onclick = () => previewCompany({ id: Number(b.dataset.previewCo), name: b.dataset.previewName })));
  el.querySelectorAll("[data-co-profile]").forEach((b) => (b.onclick = () => {
    const id = b.dataset.coProfile;
    const box = el.querySelector(`[data-profile-box="${id}"]`);
    const show = box.classList.contains("hidden");
    box.classList.toggle("hidden", !show);
    b.setAttribute("aria-expanded", String(show));
    b.textContent = show ? "Hide company profile" : "Company profile";
    if (show && !box.dataset.mounted) {
      box.dataset.mounted = "1";
      CompanyProfile.mount(box, {
        url: `/api/admin/companies/${id}/profile`, confirmUrl: `/api/admin/companies/${id}/profile/confirm`,
        pdfUrl: `/api/admin/companies/${id}/profile.pdf`, firmsUrl: "/api/admin/firms",
        trackerUrl: `/api/admin/companies/${id}/tracker`, // staff-only tracker panel
        onSaved: (prof) => {
          const small = el.querySelector(`#co-${id} .co-legal`);
          if (small) small.textContent = prof.company.legal_name || "";
        },
      });
    }
  }));
  const tools = $("profileTools");
  if (tools) tools.addEventListener("toggle", () => { if (tools.open && !tools.dataset.loaded) { tools.dataset.loaded = "1"; loadProfileTools(tools.querySelector("[data-profile-tools]")); } });
  el.querySelectorAll("[data-founder-form]").forEach((f) => {
    const payload = () => {
      const fd = new FormData(f);
      return { full_name: fd.get("full_name"), email: fd.get("email"), title: fd.get("title") || null, phone: fd.get("phone") || null,
        note: fd.get("note") || null, send_email: fd.get("send_email") === "on" };
    };
    f.querySelector("[data-invite-preview]").onclick = async () => {
      const data = payload();
      const nameIn = f.querySelector('[name="full_name"]'), mailIn = f.querySelector('[name="email"]');
      if (String(data.full_name || "").trim().length < 2) { toast("Type the founder's full name first"); nameIn.focus(); return; }
      if (!mailIn.value.trim() || !mailIn.checkValidity()) { toast("Type a valid email address, like name@example.com"); mailIn.focus(); return; }
      let pv;
      try {
        pv = await PortalAPI.json("/api/admin/messages/invite-preview", { method: "POST", body: JSON.stringify({ company_id: Number(f.dataset.founderForm), full_name: data.full_name.trim(), email: data.email.trim(), note: data.note }) });
      } catch (err) {
        toast(err.message);
        return;
      }
      document.getElementById("invitePreview")?.remove();
      const dlg = document.createElement("div");
      dlg.id = "invitePreview";
      dlg.className = "invite-dialog";
      dlg.innerHTML = `<div class="invite-dialog-card card" role="dialog" aria-modal="true" aria-labelledby="invitePreviewTitle">
          <header><div><small class="eyebrow">Invite preview</small><h3 id="invitePreviewTitle">What ${esc(data.full_name.trim().split(" ")[0])} will receive</h3></div><button type="button" class="btn ghost" data-ip-close aria-label="Close preview">Close</button></header>
          <dl class="invite-meta"><div><dt>To</dt><dd>${esc(data.email.trim())}</dd></div><div><dt>Subject</dt><dd>${esc(pv.subject)}</dd></div></dl>
          <div class="invite-body">${esc(pv.body)}</div>
          ${data.phone ? `<h4>WhatsApp message</h4><div class="invite-body wa">${esc(pv.whatsapp_text)}</div>` : ""}
          <p class="muted small">${data.send_email ? (pv.email_mode === "test" ? "Email is in test mode here: the invite waits in the outbox instead of being sent." : "The email goes out as soon as you send the invite.") : "Email the invite is unticked, so you get the link to share yourself."}</p>
          <div class="row-actions"><button type="button" class="btn primary" data-ip-send>Send invite</button><button type="button" class="btn ghost" data-ip-close>Edit details</button></div>
        </div>`;
      document.body.appendChild(dlg);
      const close = () => { dlg.remove(); document.removeEventListener("keydown", onKey); f.querySelector("[data-invite-preview]").focus(); };
      const onKey = (e) => { if (e.key === "Escape") close(); };
      document.addEventListener("keydown", onKey);
      dlg.addEventListener("click", (e) => { if (e.target === dlg || e.target.closest("[data-ip-close]")) close(); });
      dlg.querySelector("[data-ip-send]").onclick = () => { close(); f.requestSubmit(); };
      dlg.querySelector("[data-ip-send]").focus();
    };
    f.onsubmit = async (e) => {
      e.preventDefault();
      const btn = f.querySelector('[type="submit"]');
      btn.disabled = true;
      try {
        const r = await PortalAPI.json(`/api/admin/companies/${f.dataset.founderForm}/founders`, { method: "POST", body: JSON.stringify(payload()) });
        await loadCompanies();
        showLink(`Founder invited to ${r.company}`, r.email, r);
      } catch (err) {
        toast(err.message);
        btn.disabled = false;
      }
    };
  });
  el.querySelectorAll("[data-team-form]").forEach((f) => {
    f.onsubmit = (e) =>
      submitJSON(e, `/api/admin/companies/${f.dataset.teamForm}/team`, "PUT", (fd) => ({ relationship_partner: fd.get("relationship_partner"), portfolio_analyst: fd.get("portfolio_analyst") }), "Demo Ventures team saved (history kept)", loadCompanies);
  });
  el.querySelectorAll("[data-playbook-form]").forEach((f) => {
    f.onsubmit = (e) =>
      submitJSON(e, `/api/admin/companies/${f.dataset.playbookForm}/playbook`, "PUT", (fd) => ({ owner_name: fd.get("owner_name") || null }), "Playbook owner saved", loadCompanies);
  });
  el.querySelectorAll("[data-tasks]").forEach((b) => {
    b.onclick = () => {
      const box = el.querySelector(`[data-tasks-box="${b.dataset.tasks}"]`);
      if (!box.classList.toggle("hidden")) loadTaskEditor(b.dataset.tasks, box);
    };
  });
  el.querySelectorAll("[data-user-action]").forEach((b) => (b.onclick = () => userAction(b.dataset.id, b.dataset.userAction, b.dataset.email, loadCompanies)));
  el.querySelectorAll("[data-contact]").forEach((b) => {
    b.onclick = () => editForm(b, `Edit founder: ${b.dataset.name}`, `
        <label>Full name<input name="full_name" required minlength="2" maxlength="120" value="${esc(b.dataset.name)}"></label>
        <label>Email${helpTip("Their sign-in address. Changing it signs them out; they sign in with the new address and their password.")}<input name="email" type="email" required maxlength="200" value="${esc(b.dataset.email)}"></label>
        <label>Role<input name="title" maxlength="80" placeholder="e.g. Co-founder & CEO" value="${esc(b.dataset.title)}"></label>
        <label>Phone for WhatsApp<input name="phone" maxlength="30" placeholder="+91 …" value="${esc(b.dataset.phone)}"></label>`,
      "Save details", async (fd) => {
        const body = {};
        const now = { full_name: fd.get("full_name"), email: fd.get("email"), title: fd.get("title"), phone: fd.get("phone") };
        const was = { full_name: b.dataset.name, email: b.dataset.email, title: b.dataset.title, phone: b.dataset.phone };
        for (const k of Object.keys(now)) if (String(now[k] || "").trim() !== String(was[k] || "").trim()) body[k] = String(now[k] || "").trim();
        if (!Object.keys(body).length) { toast("Nothing changed"); return true; }
        try {
          await PortalAPI.json(`/api/admin/users/${b.dataset.contact}`, { method: "PATCH", body: JSON.stringify(body) });
          toast("Founder details saved");
          await loadCompanies();
          return true;
        } catch (err) {
          toast(err.message);
          return false;
        }
      });
  });
  el.querySelectorAll("[data-co-status]").forEach((b) => {
    b.onclick = async () => {
      if (b.dataset.to === "exited" && !confirm(`Mark ${b.dataset.name} as exited? Its records are kept.`)) return;
      try {
        await PortalAPI.json(`/api/admin/companies/${b.dataset.coStatus}`, { method: "PATCH", body: JSON.stringify({ status: b.dataset.to }) });
        toast(b.dataset.to === "exited" ? `${b.dataset.name} marked as exited` : `${b.dataset.name} marked as active`);
        await loadCompanies();
      } catch (err) {
        toast(err.message);
      }
    };
  });
  el.querySelectorAll("[data-notes]").forEach((b) => {
    b.onclick = () => {
      const box = el.querySelector(`[data-notes-box="${b.dataset.notes}"]`);
      if (!box.classList.toggle("hidden")) loadNotes(b.dataset.notes, box);
      b.textContent = box.classList.contains("hidden") ? "Show notes" : "Hide notes";
    };
  });
  el.querySelectorAll("[data-history]").forEach((b) => {
    b.onclick = async () => {
      const box = el.querySelector(`[data-history-box="${b.dataset.history}"]`);
      if (box.classList.toggle("hidden")) return;
      try {
        const h = await PortalAPI.json(`/api/admin/companies/${b.dataset.history}/team/history`);
        box.innerHTML = h.length ? h.map((x) => `<div class="person"><span>${esc(ASSIGNMENT_LABEL[x.role] || x.role)}: <strong>${esc(x.person)}</strong><small>from ${esc(fmt(x.since))} · by ${esc(x.assigned_by || "-")}</small></span></div>`).join("") : `<p class="muted">No assignments yet.</p>`;
      } catch (err) {
        box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
      }
    };
  });
}

async function loadNotes(companyId, box) {
  let notes;
  try {
    notes = await PortalAPI.json(`/api/admin/companies/${companyId}/notes`);
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  box.innerHTML = `<form class="inline-form" data-note-form style="margin:.6rem 0">
      <select id="nk-${companyId}" name="kind" aria-label="Type">${[["note", "Note"], ["call", "Call"], ["meeting", "Meeting"], ["email", "Email"]].map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
      <input id="nb-${companyId}" name="body" required minlength="3" maxlength="2000" placeholder="What was discussed or agreed" aria-label="Note">
      <button class="btn primary" type="submit">Add</button></form>
    ${notes.length ? `<div class="act-list">${notes.map((n) => `<div class="act-item"><strong>${esc(n.kind_label)} · ${esc(n.author)}</strong><span>${esc(n.body)}</span><small>${esc(fmt(n.at))}</small></div>`).join("")}</div>` : `<p class="muted">No notes yet. Record calls, meetings and decisions here.</p>`}`;
  box.querySelector("[data-note-form]").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await PortalAPI.json(`/api/admin/companies/${companyId}/notes`, { method: "POST", body: JSON.stringify({ kind: fd.get("kind"), body: fd.get("body") }) });
      toast("Note added");
      await loadNotes(companyId, box);
    } catch (err) {
      toast(err.message);
    }
  };
}

async function loadTaskEditor(companyId, box) {
  let d;
  try {
    d = await PortalAPI.json(`/api/admin/companies/${companyId}/tasks`);
  } catch (err) {
    box.innerHTML = `<p class="muted">${esc(err.message)}</p>`;
    return;
  }
  box.innerHTML = `${d.phases.map((ph) => `<div style="margin-top:.5rem"><strong style="font-size:12px">${esc(ph.label)}</strong>${d.tasks.filter((t) => t.phase_no === ph.no).map((t) => `<div class="person"><span>${t.done ? "✓ " : ""}${esc(t.title)}<small>${t.done ? `done by ${esc(t.done_by || "-")} · ${esc(fmt(t.done_at))}` : "open"}${t.resource_title ? ` · resource: ${esc(t.resource_title)}` : ""}</small></span><button class="btn ghost" type="button" data-del-task="${t.id}">Remove</button></div>`).join("") || `<p class="muted" style="margin:.25rem 0">No tasks.</p>`}</div>`).join("")}
    <form class="inline-form" data-add-task style="margin-top:.75rem">
      <select id="nt-phase-${companyId}" name="phase_no" aria-label="Phase">${d.phases.map((ph) => `<option value="${ph.no}">${esc(ph.label)}</option>`).join("")}</select>
      <input id="nt-title-${companyId}" name="title" required minlength="3" maxlength="160" placeholder="New task" aria-label="Task title">
      <select id="nt-res-${companyId}" name="resource_slug" aria-label="Linked resource"><option value="">No linked resource</option>${d.resources.map((r) => `<option value="${esc(r.slug)}">${esc(r.title)}</option>`).join("")}</select>
      <button class="btn primary" type="submit">Add task</button>
    </form>`;
  box.querySelectorAll("[data-del-task]").forEach((btn) => {
    btn.onclick = async () => {
      if (!confirm("Remove this task from the company's playbook?")) return;
      try {
        await PortalAPI.json(`/api/admin/tasks/${btn.dataset.delTask}`, { method: "DELETE" });
        toast("Task removed");
        await loadCompanies();
      } catch (err) {
        toast(err.message);
      }
    };
  });
  box.querySelector("[data-add-task]").onsubmit = (e) =>
    submitJSON(e, `/api/admin/companies/${companyId}/tasks`, "POST", (fd) => ({ phase_no: Number(fd.get("phase_no")), title: fd.get("title"), resource_slug: fd.get("resource_slug") || null }), "Task added to the founder's playbook", loadCompanies);
}

/* ---------------- Activity tracker */
const activityState = { kind: null, person: null };
async function loadActivity() {
  const el = $("tab-activity");
  const kinds = [["founder", "Founders", "activity.founders"], ["analyst", "Analysts", "activity.analysts"], ["admin", "Admins", "activity.admins"]].filter(([, , p]) => can(p));
  if (!activityState.kind || !kinds.some(([k]) => k === activityState.kind)) activityState.kind = kinds[0][0];
  let people;
  try {
    people = await PortalAPI.json(`/api/admin/activity?kind=${activityState.kind}`);
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  const founders = activityState.kind === "founder";
  el.innerHTML = `
    
    <div class="subtabs" role="tablist">${kinds.map(([k, l]) => `<button type="button" role="tab" class="subtab${k === activityState.kind ? " active" : ""}" aria-selected="${k === activityState.kind}" data-akind="${k}">${l}</button>`).join("")}</div>
    <div class="card"><div class="scroll"><table class="data"><thead><tr><th>Person</th><th>${founders ? "Company" : "Companies"}</th><th>Last sign-in</th><th class="num">Sign-ins (30 days)</th>${founders ? `<th class="num">Downloads</th><th class="num">Requests</th><th>Questionnaire</th>` : `<th class="num">Actions (30 days)</th>`}<th></th></tr></thead><tbody>
      ${people.map((p) => `<tr><td><strong>${esc(p.full_name)}</strong><br><small class="muted">${esc(p.email)}</small>${p.active ? "" : ` <span class="pill off">Inactive</span>`}</td>
        <td>${esc(founders ? p.company : (p.companies || []).join(", ") || "-")}</td><td>${esc(fmt(p.last_sign_in))}</td><td class="num">${p.sign_ins_30d}</td>
        ${founders ? `<td class="num">${p.downloads}</td><td class="num">${p.requests}</td><td>${p.questionnaire_done ? "Done" : "-"}</td>` : `<td class="num">${p.actions_30d}</td>`}
        <td><button class="btn ghost" type="button" data-person="${p.id}">View activity</button></td></tr>`).join("") || `<tr><td colspan="8" class="muted">Nobody to show yet.</td></tr>`}
    </tbody></table></div></div>
    <div id="personTimeline"></div>`;
  el.querySelectorAll("[data-akind]").forEach((b) => (b.onclick = () => { activityState.kind = b.dataset.akind; loadActivity(); }));
  el.querySelectorAll("[data-person]").forEach((b) => (b.onclick = () => showTimeline(b.dataset.person)));
}

async function showTimeline(personId) {
  const box = $("personTimeline");
  try {
    const d = await PortalAPI.json(`/api/admin/activity/${personId}`);
    box.innerHTML = `<div class="card" style="margin-top:1rem"><h3 style="margin-top:0">${esc(d.person.full_name)} <small class="muted">${esc(d.person.email)}</small></h3>
      ${d.timeline.length ? `<div class="act-list">${d.timeline.map((t) => `<div class="act-item"><strong>${esc(t.what)}</strong>${t.target ? ` · ${esc(t.target)}` : ""}<small>${esc(fmt(t.at))}</small></div>`).join("")}</div>` : `<p class="muted">No activity yet.</p>`}</div>`;
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    toast(err.message);
  }
}

/* ---------------- Audit trail (Super Admin: everything; Admin: their companies) */
let auditKind = "all";
function auditRow(a) {
  return `<div class="audit-row"><span class="muted">${esc(fmt(a.at))}</span><span><strong>${esc(a.what || a.action)}</strong></span><span>${esc(a.target || "")}${a.company ? ` <span class="pill">${esc(a.company)}</span>` : ""} <small class="muted">· ${esc(a.actor_name || a.actor)}</small></span></div>`;
}
async function loadAudit() {
  const el = $("tab-audit");
  let rows;
  try {
    rows = await PortalAPI.json(`/api/admin/audit?kind=${auditKind}`);
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  el.innerHTML = `
    
    <div class="subtabs" role="tablist">${[["all", "Everything"], ["changes", "Changes"], ["downloads", "Downloads"]].map(([k, l]) => `<button type="button" role="tab" class="subtab${k === auditKind ? " active" : ""}" aria-selected="${k === auditKind}" data-audit-kind="${k}">${l}</button>`).join("")}</div>
    <div class="card">${rows.length ? rows.map(auditRow).join("") : `<p class="muted">Nothing recorded yet.</p>`}</div>`;
  el.querySelectorAll("[data-audit-kind]").forEach((b) => (b.onclick = () => { auditKind = b.dataset.auditKind; loadAudit(); }));
}

/* ---------------- Bulk upload from a CSV (resources and Connect profiles) */
function bulkPanel(box, opts) {
  $("uploadPanel")?.classList.add("hidden"); // one panel at a time
  box.classList.toggle("hidden");
  if (box.classList.contains("hidden")) return;
  setTimeout(() => box.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  box.innerHTML = `<h3 style="margin-top:0">${esc(opts.title)}</h3>
    <ol class="muted" style="margin:.2rem 0 .8rem;padding-left:1.2rem;font-size:13px"><li><a href="#" data-template>Download the template</a> and fill one row per ${esc(opts.noun)}. It opens in Excel; save it as CSV or Excel.</li>${opts.withFiles ? `<li>Select the CSV and every file it names (column <code>file_name</code>).</li>` : `<li>Select the filled CSV.</li>`}<li><strong>Check</strong> first: nothing is saved until every row is valid. Then <strong>Save</strong>.</li></ol>
    <form class="review-form" data-bulk-form>
      <label class="full">Spreadsheet (CSV or Excel)<input name="sheet" type="file" accept=".csv,.xlsx,text/csv" required></label>
      ${opts.withFiles ? `<label class="full">Files named in the spreadsheet<input name="files" type="file" multiple accept=".pdf,.docx,.xlsx,.pptx,.csv"></label>` : ""}
      <div class="full review-actions"><button class="btn ghost" type="submit" data-mode="check">Check</button><button class="btn primary" type="submit" data-mode="save" disabled>Save</button><button class="btn ghost" type="button" data-bulk-close>Close</button></div>
    </form>
    <div data-bulk-result></div>`;
  box.querySelector("[data-template]").onclick = async (e) => { e.preventDefault(); try { await PortalAPI.download(opts.template); } catch (err) { toast(err.message); } };
  box.querySelector("[data-bulk-close]").onclick = () => box.classList.add("hidden");
  const form = box.querySelector("[data-bulk-form]");
  let mode = "check";
  form.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => (mode = b.dataset.mode)));
  form.onchange = () => (form.querySelector('[data-mode="save"]').disabled = true);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData();
    fd.append(opts.sheetField, form.sheet.files[0]);
    if (opts.withFiles) [...form.files.files].forEach((f) => fd.append("files", f));
    fd.append("dry_run", mode === "check" ? "true" : "false");
    try {
      const resp = await PortalAPI.request(opts.endpoint, { method: "POST", body: fd });
      const r = await resp.json().catch(() => ({}));
      if (!resp.ok || !Array.isArray(r.rows)) throw new Error(typeof r.detail === "string" ? r.detail : "The file could not be read. Download the template and try again.");
      const result = box.querySelector("[data-bulk-result]");
      result.innerHTML = `<div class="scroll"><table class="data"><thead><tr><th>Row</th><th>${esc(opts.noun)}</th><th>Check</th></tr></thead><tbody>${r.rows.map((row) => `<tr><td class="num">${row.row}</td><td>${esc(row.title || row.name || row.full_name || "")}</td><td>${row.errors.length ? `<span class="pill warn">Fix</span> ${esc(row.errors.join("; "))}` : `<span class="pill on">OK</span>`}</td></tr>`).join("")}</tbody></table></div>`;
      if (mode === "check") {
        form.querySelector('[data-mode="save"]').disabled = !r.ok;
        toast(r.ok ? `All ${r.rows.length} rows are valid. Click Save.` : "Some rows need fixing: see the table.");
      } else if (r.saved) {
        toast(`${r.saved} saved. They wait for the Super Admin's approval.`);
        box.classList.add("hidden");
        await opts.reload();
      }
    } catch (err) {
      toast(err.message);
    }
  };
}

/* ---------------- Sector updates (written by hand in alpha) */
async function loadUpdates() {
  const el = $("tab-updates");
  let rows, companies;
  try {
    [rows, companies] = await Promise.all([PortalAPI.json("/api/admin/sector-updates"), PortalAPI.json("/api/admin/companies"), loadAudienceOptions(true)]);
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  const labelOpts = ["POLICY", "REGULATORY", "MARKET", "FUNDING", "EVENT"].map((l) => `<option value="${l}">${l.charAt(0) + l.slice(1).toLowerCase()}</option>`).join("");
  el.innerHTML = `
    
    <div class="card section"><h3 style="margin-top:0">Add a sector update</h3>
      <form id="updateForm" class="review-form">
        <label>Topic${helpTip("Founders group and filter updates by topic.")}<select id="su-label" name="label">${labelOpts}</select></label>
        <label>Show it for${helpTip("After this, the update leaves founders' feeds. It stays in this list.")}<select id="su-days" name="expires_in_days">${[[7, "1 week"], [14, "2 weeks"], [30, "30 days"], [60, "60 days"], [90, "90 days"], [180, "6 months"]].map(([d, l]) => `<option value="${d}"${d === 30 ? " selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="full">Headline<input id="su-title" name="title" required minlength="5" maxlength="160"></label>
        <label class="full">What it means for the founder${helpTip("Two or three sentences: what happened and why it matters to this company.")}<textarea id="su-summary" name="summary" required minlength="10" maxlength="800" rows="3"></textarea></label>
        <label>Source${helpTip("Who published it, for example Ministry of Heavy Industries.")}<input id="su-source" name="source" required minlength="2" maxlength="120" placeholder="e.g. Ministry of Heavy Industries"></label>
        <label>Source link<input id="su-url" name="source_url" type="url" maxlength="500" placeholder="https://"></label>
        ${audiencePicker({ company_id: companies[0]?.id }, "Which founders see it")}
        <div class="full review-actions"><button class="btn primary" type="submit">Save update</button></div>
      </form></div>
    <div class="card"><h3 style="margin-top:0">Updates</h3><div class="scroll"><table class="data"><thead><tr><th>Update</th><th>Who sees it</th><th>Source</th><th>Visible until</th><th></th></tr></thead><tbody>
      ${rows.map((u) => `<tr><td><span class="pill">${esc(u.label)}</span> ${esc(u.title)}${approvalPill(u.approval)}<br><small class="muted">${esc(fmt(u.published_at))} · ${esc(u.published_by || "Demo Ventures")}${u.review_note ? ` · note: ${esc(u.review_note)}` : ""}</small></td><td>${esc(u.company || "-")}</td><td>${u.source_url ? `<a href="${esc(u.source_url)}" target="_blank" rel="noopener noreferrer">${esc(u.source)}</a>` : esc(u.source || "-")}</td><td>${u.live ? esc(fmt(u.expires_at)) : `<span class="pill off">Expired or withdrawn</span>`}</td><td><div class="row-actions">${u.can_change && u.approval === "returned" ? `<button class="btn primary" type="button" data-resub-update="${u.id}">Edit and resubmit</button>` : ""}${u.can_change && u.live ? `<button class="btn ghost" type="button" data-withdraw="${u.id}">Withdraw</button>` : ""}</div></td></tr>`).join("") || `<tr><td colspan="5" class="muted">No updates yet.</td></tr>`}
    </tbody></table></div></div>`;
  wireAudience($("updateForm"));
  $("updateForm").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const aud = readAudience(e.target);
    if (audienceIncomplete(aud, e.target)) { toast("Choose who the update is for"); return; }
    try {
      const r = await PortalAPI.json("/api/admin/sector-updates", { method: "POST", body: JSON.stringify({ ...aud, label: fd.get("label"), title: fd.get("title"), summary: fd.get("summary"), source: fd.get("source"), source_url: fd.get("source_url") || null, expires_in_days: Number(fd.get("expires_in_days")) }) });
      toast(afterAdd(r.approval, "Published. The founder sees it on their dashboard."));
      await loadUpdates();
    } catch (err) {
      toast(err.message);
    }
  };
  el.querySelectorAll("[data-resub-update]").forEach((b) => {
    b.onclick = async () => {
      const u = rows.find((x) => x.id == b.dataset.resubUpdate);
      const summary = await askInline(b, { label: `Corrected summary${u.review_note ? ` (note: ${u.review_note})` : ""}`, value: u.summary || "", multiline: true, required: true, save: "Resubmit for approval" });
      if (summary === null) return;
      try {
        await PortalAPI.json(`/api/admin/sector-updates/${u.id}`, { method: "PATCH", body: JSON.stringify({ action: "resubmit", summary }) });
        toast("Resubmitted. It waits for the Super Admin's approval.");
        await loadUpdates();
      } catch (err) {
        toast(err.message);
      }
    };
  });
  el.querySelectorAll("[data-withdraw]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Withdraw this update from the founder's dashboard?")) return;
      try {
        await PortalAPI.json(`/api/admin/sector-updates/${b.dataset.withdraw}`, { method: "PATCH", body: JSON.stringify({ action: "withdraw" }) });
        toast("Withdrawn");
        await loadUpdates();
      } catch (err) {
        toast(err.message);
      }
    };
  });
}

/* ---------------- Events */
/* When fields (partner review, 4 Nov 2026): a date, a time with AM/PM, and a length from a list, including
   "Ends on another day" for multi-day programmes. readWhen() gives {starts_at, duration_minutes} in IST. */
const DURATIONS = [[30, "30 minutes"], [45, "45 minutes"], [60, "1 hour"], [90, "1 hour 30 minutes"], [120, "2 hours"], [180, "3 hours"],
  [240, "Half day (4 hours)"], [480, "Full day (8 hours)"]];
function whenFields(iso, minutes = 60) {
  const local = iso ? istInput(iso) : "";
  const date = local.slice(0, 10);
  const [hh, mm] = local ? local.slice(11, 16).split(":").map(Number) : [10, 0];
  const h12 = ((hh + 11) % 12) + 1, ampm = hh >= 12 ? "PM" : "AM";
  const multi = minutes && !DURATIONS.some(([m]) => m === minutes);
  const end = iso && multi ? istInput(new Date(new Date(iso).getTime() + minutes * 60000).toISOString()) : "";
  const eh = end ? Number(end.slice(11, 13)) : 18, em = end ? Number(end.slice(14, 16)) : 0;
  const timeSel = (prefix, h, m, ap) => `<span class="time-pick"><select name="${prefix}_h" aria-label="Hour">${Array.from({ length: 12 }, (_, i) => i + 1).map((n) => `<option${n === h ? " selected" : ""}>${n}</option>`).join("")}</select><span>:</span><select name="${prefix}_m" aria-label="Minutes">${[0, 15, 30, 45].map((n) => `<option value="${n}"${n === m - (m % 15) ? " selected" : ""}>${String(n).padStart(2, "0")}</option>`).join("")}</select><select name="${prefix}_ap" aria-label="AM or PM"><option${ap === "AM" ? " selected" : ""}>AM</option><option${ap === "PM" ? " selected" : ""}>PM</option></select></span>`;
  return `<div class="full when-fields" data-when>
    <label>Date${helpTip("The day the event starts. All times are IST.")}<input type="date" name="when_date" required value="${esc(date)}"></label>
    <label>Starts at (IST)${timeSel("when", h12, mm, ampm)}</label>
    <label>Length${helpTip("How long it runs. Choose Ends on another day for a programme over several days.")}<select name="when_len">${DURATIONS.map(([m, l]) => `<option value="${m}"${m === minutes ? " selected" : ""}>${l}</option>`).join("")}<option value="multi"${multi ? " selected" : ""}>Ends on another day…</option></select></label>
    <label data-when-end class="${multi ? "" : "hidden"}">Last day<input type="date" name="when_end_date" value="${esc(end.slice(0, 10))}"></label>
    <label data-when-end class="${multi ? "" : "hidden"}">Ends at (IST)${timeSel("when_end", ((eh + 11) % 12) + 1, em, eh >= 12 ? "PM" : "AM")}</label>
  </div>`;
}
function wireWhen(root) {
  const box = root.querySelector("[data-when]");
  if (!box) return;
  const len = box.querySelector('[name="when_len"]');
  const sync = () => box.querySelectorAll("[data-when-end]").forEach((n) => n.classList.toggle("hidden", len.value !== "multi"));
  len.addEventListener("change", sync);
  sync();
}
function readWhen(fd) {
  const to24 = (h, ap) => (Number(h) % 12) + (ap === "PM" ? 12 : 0);
  const pad = (n) => String(n).padStart(2, "0");
  const date = fd.get("when_date");
  if (!date) throw new Error("Choose the event's date");
  const start = `${date}T${pad(to24(fd.get("when_h"), fd.get("when_ap")))}:${pad(fd.get("when_m"))}`;
  let minutes = Number(fd.get("when_len"));
  if (fd.get("when_len") === "multi") {
    const endDate = fd.get("when_end_date");
    if (!endDate) throw new Error("Choose the last day of the event");
    const end = `${endDate}T${pad(to24(fd.get("when_end_h"), fd.get("when_end_ap")))}:${pad(fd.get("when_end_m"))}`;
    minutes = Math.round((new Date(end + ":00+05:30") - new Date(start + ":00+05:30")) / 60000);
    if (minutes < 15) throw new Error("The event must end after it starts");
    if (minutes > 10080) throw new Error("An event can run for at most 7 days");
  }
  return { starts_at: start, duration_minutes: minutes };
}
const istLocal = (iso) => new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" }) + " IST";

async function loadEvents() {
  const el = $("tab-events");
  let rows, companies;
  try {
    [rows, companies] = await Promise.all([PortalAPI.json("/api/admin/events"), PortalAPI.json("/api/admin/companies"), loadAudienceOptions(true)]);
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  el.innerHTML = `
    <div class="card section"><h3 style="margin-top:0">Add an event</h3>
      <form id="eventForm" class="review-form">
        <label class="full">Title<input id="ev-title" name="title" required minlength="3" maxlength="160"></label>
        ${whenFields(null, 60)}
        <label class="full">Location<input id="ev-loc" name="location" required minlength="2" maxlength="160" placeholder="Online, or venue and city"></label>
        ${audiencePicker({}, "Who is invited")}
        <label>Join link or meeting ID (optional)${helpTip("For online sessions. Founders get a Join button.")}<input id="ev-link" name="join_link" maxlength="500" placeholder="https://meet.google.com/… or a meeting ID"></label>
        <label>External RSVP link (optional)${helpTip("For an event someone else runs, for example on Luma: paste its RSVP page. Founders RSVP there instead of in the portal.")}<input id="ev-rsvp" name="rsvp_url" type="url" maxlength="500" placeholder="https://lu.ma/…"></label>
        <label class="full">Description<textarea id="ev-desc" name="description" maxlength="800" rows="2"></textarea></label>
        <div class="full review-actions"><button class="btn primary" type="submit">Save event</button><small class="muted">${can("content.approve") ? "Founders can RSVP straight away." : "Founders see it once the Super Admin approves it."}</small></div>
      </form></div>
    <div class="card"><h3 style="margin-top:0">Events</h3><div class="scroll"><table class="data"><thead><tr><th>Event</th><th>When</th><th>Audience</th><th>RSVPs</th><th></th></tr></thead><tbody>
      ${rows.map((ev) => `<tr><td>${esc(ev.title)}${ev.active ? "" : ` <span class="pill off">Cancelled</span>`}${approvalPill(ev.approval)}<br><small class="muted">${esc(ev.location || "")}${ev.review_note ? ` · note: ${esc(ev.review_note)}` : ""}</small>${ev.past ? "" : `<br><small>Join: ${ev.join_link ? (/^https?:\/\//.test(ev.join_link) ? `<a href="${esc(ev.join_link)}" target="_blank" rel="noopener noreferrer">${esc(ev.join_link)}</a>` : esc(ev.join_link)) : `<span class="muted">no link yet</span>`}</small>`}${ev.rsvp_url ? `<br><small>External RSVP: <a href="${esc(ev.rsvp_url)}" target="_blank" rel="noopener noreferrer">${esc(ev.rsvp_url)}</a></small>` : ""}${ev.pending_join_link ? `<br><span class="pill warn">New join link waiting for approval</span> <small class="muted">${esc(ev.pending_join_link)} · by ${esc(ev.pending_link_by || "-")}</small>` : ""}</td><td>${esc(istLocal(ev.starts_at))}${ev.past ? `<br><span class="pill">Past</span>` : ""}</td><td>${esc(ev.audience)}</td><td class="num">${ev.attendees.length}${ev.attendees.length ? `<br><small class="muted">${ev.attendees.map(esc).join(", ")}</small>` : ""}</td><td><div class="row-actions">${ev.approval === "returned" ? `<button class="btn primary" type="button" data-ev-resub="${ev.id}">Edit and resubmit</button>` : ""}${!ev.past && (can("content.approve") || ev.created_by === me.full_name) ? `<button class="btn ghost" type="button" data-ev-edit="${ev.id}">Edit details</button>` : ""}${can("content.approve") || ev.created_by === me.full_name ? (ev.active ? `<button class="btn ghost" type="button" data-ev="${ev.id}" data-ev-action="cancel">Cancel</button>` : `<button class="btn ghost" type="button" data-ev="${ev.id}" data-ev-action="restore">Restore</button>`) : ""}${ev.past ? "" : `<button class="btn ghost" type="button" data-ev-link="${ev.id}" data-link="${esc(ev.join_link || "")}">${ev.join_link ? "Change join link" : "Add join link"}</button>`}</div></td></tr>`).join("") || `<tr><td colspan="5" class="muted">No events yet.</td></tr>`}
    </tbody></table></div></div>`;
  wireAudience($("eventForm"));  // show only the audience options for the chosen "Send to", with a live count
  wireWhen($("eventForm"));
  $("eventForm").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const aud = readAudience(e.target);
      if (audienceIncomplete(aud, e.target)) { toast("Choose who is invited"); return; }
      const when = readWhen(fd);
      const r = await PortalAPI.json("/api/admin/events", { method: "POST", body: JSON.stringify({ ...aud, title: fd.get("title"), ...when, location: fd.get("location"), description: fd.get("description") || null, join_link: fd.get("join_link") || null, rsvp_url: fd.get("rsvp_url") || null }) });
      toast(afterAdd(r.approval, "Event published. Founders can RSVP now."));
      await loadEvents();
    } catch (err) {
      toast(err.message);
    }
  };
  const patch = async (id, body, msg) => {
    try {
      await PortalAPI.json(`/api/admin/events/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      toast(msg);
      await loadEvents();
    } catch (err) {
      toast(err.message);
    }
  };
  el.querySelectorAll("[data-ev-action]").forEach((b) => {
    b.onclick = () => {
      if (b.dataset.evAction === "cancel" && !confirm("Cancel this event? Founders will no longer see it.")) return;
      patch(b.dataset.ev, { action: b.dataset.evAction }, b.dataset.evAction === "cancel" ? "Event cancelled" : "Event restored");
    };
  });
  el.querySelectorAll("[data-ev-edit]").forEach((b) => {
    b.onclick = () => {
      const ev = rows.find((x) => x.id == b.dataset.evEdit);
      const minutes = Math.max(15, Math.round((new Date(ev.ends_at || ev.starts_at) - new Date(ev.starts_at)) / 60000)) || 60;
      editForm(b, `Edit event: ${ev.title}`, `
        <label class="full">Title<input name="title" required minlength="3" maxlength="160" value="${esc(ev.title)}"></label>
        ${whenFields(ev.starts_at, minutes)}
        <label>Location<input name="location" required minlength="2" maxlength="160" value="${esc(ev.location || "")}"></label>
        <label>External RSVP link (optional)${helpTip("Leave empty for founders to RSVP in the portal.")}<input name="rsvp_url" type="url" maxlength="500" value="${esc(ev.rsvp_url || "")}" placeholder="https://lu.ma/…"></label>
        ${audiencePicker(ev, "Who is invited")}
        <label class="full">Description<textarea name="description" maxlength="800" rows="2">${esc(ev.description || "")}</textarea></label>
        <small class="full muted">${can("content.approve") ? "Changes are live for founders at once." : "Founders see the changes once the Super Admin approves them; until then the event is hidden from founders."}</small>`,
        "Save changes", async (fd) => {
          const form = document.querySelector(".inline-edit-form");
          const aud = readAudience(form);
          if (audienceIncomplete(aud, form)) { toast("Choose who is invited"); return false; }
          let when;
          try { when = readWhen(fd); } catch (err) { toast(err.message); return false; }
          const body = { action: "edit", title: fd.get("title"), location: fd.get("location"), description: fd.get("description") || "",
            duration_minutes: when.duration_minutes, rsvp_url: fd.get("rsvp_url") || "",
            ...(aud.company_id ? { company_id: aud.company_id } : { for_all_founders: true, target_company_ids: aud.target_company_ids, target_sectors: aud.target_sectors, target_stages: aud.target_stages }) };
          if (when.starts_at !== istInput(ev.starts_at)) body.starts_at = when.starts_at;
          try {
            await PortalAPI.json(`/api/admin/events/${ev.id}`, { method: "PATCH", body: JSON.stringify(body) });
            toast(can("content.approve") ? "Event updated" : "Event updated; it waits for the Super Admin's approval");
            await loadEvents();
            return true;
          } catch (err) {
            toast(err.message);
            return false;
          }
        });
    };
  });
  el.querySelectorAll("[data-ev-resub]").forEach((b) => {
    b.onclick = async () => {
      const ev = rows.find((x) => x.id == b.dataset.evResub);
      const description = await askInline(b, { label: `Corrected description${ev.review_note ? ` (note: ${ev.review_note})` : ""}`, value: ev.description || "", multiline: true, required: true, save: "Resubmit for approval" });
      if (description !== null) patch(ev.id, { action: "resubmit", description }, "Resubmitted. It waits for the Super Admin's approval.");
    };
  });
  el.querySelectorAll("[data-ev-rec]").forEach((b) => {
    b.onclick = async () => {
      const url = await askInline(b, { label: "Recording link", value: b.dataset.rec || "", placeholder: "https://…", hint: "Leave empty to remove the recording.", save: "Save recording" });
      if (url !== null) patch(b.dataset.evRec, { recording_url: url }, !url ? "Recording removed" : can("content.approve") ? "Recording published to founders" : "Recording sent for approval");
    };
  });
  el.querySelectorAll("[data-ev-link]").forEach((b) => {
    b.onclick = async () => {
      const approver = can("content.approve");
      const link = await askInline(b, {
        label: "Join link or meeting ID", value: b.dataset.link || "", placeholder: "https://meet.google.com/abc-defg-hij, a Zoom or Teams link, or a meeting ID",
        hint: approver ? "Founders see a Join button straight away. Leave empty to remove the link." : "Founders keep seeing the event; the new link appears once the Super Admin approves it.",
        required: !approver, save: "Save join link",
      });
      if (link !== null) patch(b.dataset.evLink, { join_link: link }, approver ? (link ? "Join link saved. Founders see the Join button now." : "Join link removed") : "Join link sent for approval");
    };
  });
}

/* ---------------- Connect directory */
const CONNECT_GROUPS = ["Operational Support Network", "Peer Founder Network", "Investor & Fundraising Ecosystem", "Demo Ventures Network"];
// About 1,600 profiles: the list is searched, filtered by section and shown 50 at a time.
let cnQuery = "", cnSection = "", cnShown = 50;
async function loadConnect() {
  const el = $("tab-connect");
  let rows;
  try {
    rows = await PortalAPI.json("/api/admin/connect");
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  el.innerHTML = `
    
    <div class="filters section"><button class="btn primary" type="button" data-cn-new>+ Add a profile</button><button class="btn ghost" type="button" data-cn-bulk>Bulk upload (CSV or Excel)</button></div>
    <div id="connectBulk" class="card hidden" style="margin-bottom:1rem"></div>
    <div id="connectNew" class="card hidden" style="margin-bottom:1rem"><h3 style="margin-top:0">Add a Connect profile</h3>
      <form id="connectForm" class="review-form">
        <label>Network<select id="cn-group" name="network_group">${CONNECT_GROUPS.map((g) => `<option>${esc(g)}</option>`).join("")}</select></label>
        <label>Sub-section<input id="cn-sub" name="subcategory" required minlength="2" maxlength="80" placeholder="e.g. CA & Tax"></label>
        <label>Name<input id="cn-name" name="display_name" required minlength="2" maxlength="120"></label>
        <label>Role<input id="cn-role" name="role_title" required minlength="2" maxlength="120"></label>
        <label>Organisation<input id="cn-org" name="organization" required minlength="2" maxlength="120"></label>
        <label>Skills (comma-separated)<input id="cn-skills" name="skills" maxlength="200" placeholder="GST, FEMA, startup tax"></label>
        <label>Website (optional)<input id="cn-site" name="website" type="url" maxlength="300" placeholder="https://example.com"></label>
        <label>Stage (investors)${helpTip("The stages an investor backs, for example Seed, Series A.")}<input id="cn-stage" name="stage" maxlength="120" placeholder="e.g. Seed, Series A"></label>
        <label>Cheque size (investors)<input id="cn-cheque" name="cheque_size" maxlength="60" placeholder="e.g. $1–3M"></label>
        <label class="full">Note for founders (optional)<textarea id="cn-about" name="about" maxlength="600" rows="2"></textarea></label>
        <div class="full review-actions"><button class="btn primary" type="submit">Save profile</button></div>
      </form></div>
    <div class="filters section connect-admin-filters"><input id="cn-search" style="flex:1 1 240px;min-width:0;max-width:100%" type="search" maxlength="80" placeholder="Search profiles by name, section, place or tag" aria-label="Search Connect profiles" value="${esc(cnQuery)}">
      <select id="cn-filter" style="flex:1 1 240px;min-width:0;max-width:100%;width:100%" aria-label="Filter by section"><option value="">All sections (${rows.length})</option>${[...new Set(rows.map((r) => `${r.network_group}|${r.subcategory || ""}`))].map((k) => { const [g, sub] = k.split("|"); const n = rows.filter((r) => r.network_group === g && (r.subcategory || "") === sub).length; return `<option value="${esc(k)}"${k === cnSection ? " selected" : ""}>${esc(sub || "-")} · ${esc(g)} (${n})</option>`; }).join("")}</select></div>
    <div id="connectList"></div>`;
  const listBox = $("connectList");
  const drawList = () => {
    const words = cnQuery.toLowerCase().split(/\s+/).filter(Boolean);
    const match = rows.filter((r) => (!cnSection || `${r.network_group}|${r.subcategory || ""}` === cnSection)
      && words.every((w) => [r.display_name, r.subcategory, r.role_title, r.organization, r.network_group, ...(r.skills || [])].join(" ").toLowerCase().includes(w)));
    const shown = match.slice(0, cnShown);
    const visible = rows.filter((r) => r.active && r.approval === "approved").length;
    listBox.innerHTML = `<div class="card" style="margin-bottom:1rem"><h3 style="margin-top:0">Connect profiles <small class="muted">(${visible} of ${rows.length} shown to founders · ${match.length} match${match.length === 1 ? "es" : ""} · showing ${shown.length})</small></h3>${shown.map((r) => `<div class="person"><span>${esc(r.display_name)}${approvalPill(r.approval)}<small>${esc(r.subcategory || "-")} · ${esc(r.role_title || "")} · ${esc(r.organization || "")} · ${r.introductions} introduction request${r.introductions === 1 ? "" : "s"}${r.review_note ? ` · note: ${esc(r.review_note)}` : ""}</small></span><span class="row-actions">${r.active ? "" : `<span class="pill off">Not listed</span>`}<button class="btn ghost" type="button" data-cn-edit="${r.id}">Edit</button></span></div>`).join("") || `<p class="muted">${rows.length ? "No profiles match." : "No profiles yet."}</p>`}${match.length > shown.length ? `<div style="text-align:center;margin-top:12px"><button class="btn ghost" type="button" data-cn-more>Show ${Math.min(50, match.length - shown.length)} more</button></div>` : ""}</div>`;
  };
  drawList();
  $("cn-search").oninput = (e) => { cnQuery = e.target.value.trim(); cnShown = 50; drawList(); };
  $("cn-filter").onchange = (e) => { cnSection = e.target.value; cnShown = 50; drawList(); };
  el.querySelector("[data-cn-new]").onclick = () => $("connectNew").classList.toggle("hidden");
  el.querySelector("[data-cn-bulk]").onclick = () => bulkPanel($("connectBulk"), { title: "Upload Connect profiles from a spreadsheet", noun: "profile", template: "/api/admin/connect/bulk-template", endpoint: "/api/admin/connect/bulk", sheetField: "file", withFiles: false, reload: loadConnect });
  $("connectForm").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const r = await PortalAPI.json("/api/admin/connect", { method: "POST", body: JSON.stringify({ network_group: fd.get("network_group"), subcategory: fd.get("subcategory"), display_name: fd.get("display_name"), role_title: fd.get("role_title"), organization: fd.get("organization"), about: fd.get("about"), website: String(fd.get("website") || "").trim(), stage: String(fd.get("stage") || "").trim(), cheque_size: String(fd.get("cheque_size") || "").trim(), skills: String(fd.get("skills") || "").split(",").map((x) => x.trim()).filter(Boolean) }) });
      toast(afterAdd(r.approval, "Profile added. Founders see it in Connect."));
      await loadConnect();
    } catch (err) {
      toast(err.message);
    }
  };
  listBox.onclick = async (ev) => {
    if (ev.target.closest("[data-cn-more]")) { cnShown += 50; drawList(); return; }
    const b = ev.target.closest("[data-cn-active]");
    const edit = ev.target.closest("[data-cn-edit]");
    if (edit) return editConnect(edit);
    if (!b) return;
    try {
      await PortalAPI.json(`/api/admin/connect/${b.dataset.cn}`, { method: "PATCH", body: JSON.stringify({ active: b.dataset.cnActive === "1" }) });
      toast(b.dataset.cnActive === "1" ? "Profile shown to founders" : "Profile hidden from founders");
      await loadConnect();
    } catch (err) {
      toast(err.message);
    }
  };
  function editConnect(b) {
    {
      const r = rows.find((x) => x.id == b.dataset.cnEdit);
      editForm(b, `Edit Connect profile: ${r.display_name}`, `
        <label>Network<select name="network_group">${CONNECT_GROUPS.map((g) => `<option${g === r.network_group ? " selected" : ""}>${esc(g)}</option>`).join("")}</select></label>
        <label>Sub-section<input name="subcategory" required minlength="2" maxlength="80" value="${esc(r.subcategory || "")}"></label>
        <label>Name<input name="display_name" required minlength="2" maxlength="120" value="${esc(r.display_name)}"></label>
        <label>Role<input name="role_title" required minlength="2" maxlength="120" value="${esc(r.role_title || "")}"></label>
        <label>Organisation<input name="organization" required minlength="2" maxlength="120" value="${esc(r.organization || "")}"></label>
        <label>Skills (comma-separated)<input name="skills" maxlength="200" value="${esc((r.skills || []).join(", "))}"></label>
        <label>Website (optional)<input name="website" type="url" maxlength="300" value="${esc(r.website || "")}" placeholder="https://example.com"></label>
        <label>Stage (investors)<input name="stage" maxlength="120" value="${esc(r.stage || "")}"></label>
        <label>Cheque size (investors)<input name="cheque_size" maxlength="60" value="${esc(r.cheque_size || "")}"></label>
        <label class="full">Note for founders (optional)<textarea name="about" maxlength="600" rows="2">${esc(r.about || "")}</textarea></label>
        <small class="full muted">${can("content.approve") ? "Changes are live for founders at once." : "Founders see the changes once the Super Admin approves them."}</small>`,
        "Save profile", async (fd) => {
          const body = {};
          for (const k of ["network_group", "subcategory", "display_name", "role_title", "organization", "about", "website", "stage", "cheque_size"]) {
            const v = String(fd.get(k) || "").trim();
            if (v !== String(k === "about" ? r.about || "" : r[k] || "")) body[k] = v;
          }
          const skills = String(fd.get("skills") || "").split(",").map((x) => x.trim()).filter(Boolean);
          if (skills.join(",") !== (r.skills || []).join(",")) body.skills = skills;
          if (!Object.keys(body).length) { toast("Nothing changed"); return true; }
          try {
            await PortalAPI.json(`/api/admin/connect/${r.id}`, { method: "PATCH", body: JSON.stringify(body) });
            toast(can("content.approve") ? "Profile updated" : "Profile updated; it waits for approval");
            await loadConnect();
            return true;
          } catch (err) {
            toast(err.message);
            return false;
          }
        });
    }
  }
}

/* ---------------- Team & access: Super Admin, Admins, Analysts */
async function loadTeam() {
  const el = $("tab-team");
  let team = [], tiers = [];
  try {
    [team, tiers] = await Promise.all([PortalAPI.json("/api/admin/team"), PortalAPI.json("/api/admin/roles")]);
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  const tierOf = (m) => (m.roles.includes("super_admin") ? "super_admin" : m.roles.includes("admin") ? "admin" : "analyst");
  const superAdmin = team.find((m) => tierOf(m) === "super_admin");
  const row = (m) => `<div class="person"><span>${esc(m.full_name)}${m.is_you ? " (you)" : ""}<small>${esc(m.email)}${m.companies.length ? ` · ${esc(m.companies.join(", "))}` : ""} · last sign-in ${esc(fmt(m.last_sign_in))}</small></span>
      <span class="row-actions"><span class="pill ${m.active ? "on" : "off"}">${m.active ? "Active" : "Inactive"}</span>
      ${m.can_manage ? `<button class="btn ghost" type="button" data-user-action="reset" data-id="${m.id}" data-email="${esc(m.email)}">Reset password</button><button class="btn ghost" type="button" data-unlock="${m.id}">Clear sign-in lock</button><button class="btn ghost" type="button" data-user-action="${m.active ? "deactivate" : "activate"}" data-id="${m.id}" data-email="${esc(m.email)}">${m.active ? "Deactivate" : "Reactivate"}</button>` : ""}
      ${can("admins.manage") && tierOf(m) === "analyst" ? `<label class="muted reports-pick" style="font-size:12px">Reports to <select id="rt-${m.id}" data-reports="${m.id}">${team.filter((a) => tierOf(a) === "admin").map((a) => `<option value="${a.id}"${a.id === m.reports_to ? " selected" : ""}>${esc(a.full_name)}</option>`).join("")}<option value=""${m.reports_to ? "" : " selected"}>Super Admin directly</option></select></label>` : ""}
      ${can("admins.manage") && tierOf(m) !== "super_admin" ? `<button class="btn ghost" type="button" data-level="${tierOf(m) === "admin" ? "analyst" : "admin"}" data-id="${m.id}" data-name="${esc(m.full_name)}">${tierOf(m) === "admin" ? "Move to Analyst" : "Make Admin"}</button>` : ""}</span></div>`;
  const list = (tier) => team.filter((m) => tierOf(m) === tier);
  el.innerHTML = `
    
    <div class="two-col">
      <div class="card"><h3 style="margin-top:0">Tier 1 · Super Admin</h3>
        ${superAdmin ? row(superAdmin) : `<p class="muted">No Super Admin is set.</p>`}
        ${can("super_admin.handover") ? `
        <details class="handover" id="handover"><summary><strong>Hand over Super Admin</strong></summary>
          <p class="muted" style="margin:.5rem 0">Moves the role to someone else, for example to Kavya Reddy. You become an Analyst straight away. If the person has no account yet, one is created with a one-time password.</p>
          <form id="handoverForm" class="review-form">
            <label class="full">New Super Admin's email<input id="ho-email" name="email" type="email" required placeholder="name@team.demo" autocomplete="off"></label>
            <label class="full">Type the email again to confirm<input id="ho-confirm" name="confirm_email" type="email" required autocomplete="off"></label>
            <label class="full">Full name (only if they have no account yet)<input id="ho-name" name="full_name" maxlength="120" placeholder="e.g. Kavya Reddy"></label>
            <div class="full row-actions"><button class="btn primary" type="submit">Hand over Super Admin</button></div>
          </form>
        </details>` : ""}
      </div>
      <div class="card"><h3 style="margin-top:0">Add a team member</h3>
        ${can("staff.manage", "admins.manage") ? `<form id="teamForm" class="review-form">
          <label class="full">Full name<input id="tm-name" name="full_name" required minlength="2" maxlength="120"></label>
          <label class="full">Email<input id="tm-email" name="email" type="email" required placeholder="name@team.demo"></label>
          <label class="full">Tier<select id="tm-level" name="level"><option value="analyst">Analyst (tier 3)</option>${can("admins.manage") ? `<option value="admin">Admin (tier 2)</option>` : ""}</select></label>
          <div class="full row-actions"><button class="btn primary" type="submit">Add</button><small class="muted">Then assign them to a company in Companies &amp; founders. A one-time password is shown once.</small></div>
        </form>` : `<p class="muted">Ask the Super Admin or your Admin to add people.</p>`}
      </div>
    </div>
    <div class="card org" style="margin-top:1rem"><h3 style="margin-top:0">Who reports to whom</h3>
      <p class="muted" style="margin:.2rem 0 .8rem">Admins report to the Super Admin; each Analyst reports to one Admin. An Admin can do everything their Analysts can, on the same companies.</p>
      <div class="org-top"><span class="pill on">Tier 1 · Super Admin</span> <strong>${esc(superAdmin ? superAdmin.full_name : "Not set")}</strong></div>
      <div class="org-branches">
        ${list("admin").map((a) => `<div class="org-branch"><div class="org-label"><span class="pill">Tier 2 · Admin</span></div>${row(a)}
          <div class="org-reports">${list("analyst").filter((m) => m.reports_to === a.id).map(row).join("") || `<p class="muted">No analysts report to ${esc(a.full_name)} yet.</p>`}</div></div>`).join("") || `<p class="muted">No admins yet.</p>`}
        ${list("analyst").some((m) => !list("admin").some((a) => a.id === m.reports_to)) ? `<div class="org-branch"><div class="org-label"><span class="pill warn">Analysts not yet under an Admin</span></div><div class="org-reports">${list("analyst").filter((m) => !list("admin").some((a) => a.id === m.reports_to)).map(row).join("")}</div></div>` : ""}
      </div></div>
    <div class="card" style="margin-top:1rem"><h3 style="margin-top:0">What each tier can do</h3><div class="scroll"><table class="data"><thead><tr><th>Tier</th><th>Can</th></tr></thead><tbody>${tiers.map((t) => `<tr><td><strong>${t.tier} · ${esc(t.name)}</strong></td><td>${t.permissions.map((p) => `<span class="pill" title="${esc(p.description)}">${esc(p.label)}${p.assigned_only ? " · own companies" : ""}</span>`).join(" ")}</td></tr>`).join("")}</tbody></table></div></div>`;
  el.querySelectorAll("[data-user-action]").forEach((b) => (b.onclick = () => userAction(b.dataset.id, b.dataset.userAction, b.dataset.email, loadTeam)));
  el.querySelectorAll("[data-reports]").forEach((sel) => {
    sel.onchange = async () => {
      try {
        await PortalAPI.json(`/api/admin/team/${sel.dataset.reports}/reports-to`, { method: "PUT", body: JSON.stringify({ manager_id: sel.value ? Number(sel.value) : null }) });
        toast(`Now reports to ${sel.options[sel.selectedIndex].text}`);
        await loadTeam();
      } catch (err) {
        toast(err.message);
      }
    };
  });
  el.querySelectorAll("[data-level]").forEach((b) => {
    b.onclick = async () => {
      const to = b.dataset.level === "admin" ? "Admin" : "Analyst";
      if (!confirm(`Make ${b.dataset.name} an ${to}?`)) return;
      try {
        await PortalAPI.json(`/api/admin/team/${b.dataset.id}/level`, { method: "PUT", body: JSON.stringify({ level: b.dataset.level }) });
        toast(`${b.dataset.name} is now an ${to}`);
        await loadTeam();
      } catch (err) {
        toast(err.message);
      }
    };
  });
  if ($("teamForm"))
    $("teamForm").onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      try {
        const r = await PortalAPI.json("/api/admin/team", { method: "POST", body: JSON.stringify({ full_name: fd.get("full_name"), email: fd.get("email"), level: fd.get("level") }) });
        await loadTeam();
        showSecret(`${ROLE_NAMES[r.roles[0]]} account created`, r.email, r.temporary_password);
      } catch (err) {
        toast(err.message);
      }
    };
  if ($("handoverForm"))
    $("handoverForm").onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const email = String(fd.get("email") || "").trim();
      if (!confirm(`Hand the Super Admin role to ${email}? You will become an Analyst immediately.`)) return;
      try {
        const r = await PortalAPI.json("/api/admin/super-admin/handover", {
          method: "POST",
          body: JSON.stringify({ email, confirm_email: fd.get("confirm_email"), full_name: fd.get("full_name") || null }),
        });
        const note = `${r.super_admin.full_name} (${r.super_admin.email}) is now the Super Admin. You are an Analyst.`;
        try { sessionStorage.setItem("frp_ws_notice", note + (r.temporary_password ? ` One-time password for them: ${r.temporary_password}` : "")); } catch (_) {}
        location.reload();
      } catch (err) {
        toast(err.message);
      }
    };
}

/* ---------------- My profile (every tier) */
async function loadProfile() {
  const el = $("tab-profile");
  let p;
  try {
    p = await PortalAPI.json("/api/auth/profile");
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  el.innerHTML = `
    <div class="two-col">
      <div class="card profile-card"><div class="profile-head"><div class="avatar big">${esc(p.full_name.split(" ").map((x) => x[0]).join("").slice(0, 2).toUpperCase())}</div><div><h3 style="margin:0">${esc(p.full_name)}</h3><small class="muted">${esc(p.email)}</small><br><span class="pill on">${esc(p.tier)}</span></div></div>
        <dl class="answers"><dt>Member since</dt><dd>${esc(fmt(p.member_since))}</dd><dt>Last sign-in</dt><dd>${esc(fmt(p.last_sign_in))}</dd><dt>Sign-ins, 30 days</dt><dd>${p.sign_ins_30d}</dd><dt>Companies</dt><dd>${esc((p.companies || []).join(", ") || (p.tier === "Super Admin" ? "Whole portfolio" : "None assigned yet"))}</dd></dl>
        <div class="row-actions" style="margin-top:.8rem"><button class="btn ghost" type="button" id="pwBtn">Change password</button><button class="btn ghost" type="button" id="replayJourney">Replay my walkthrough</button></div>
        <form id="pwForm" class="review-form hidden" style="margin-top:.8rem">
          <label class="full">Current password<input name="current" type="password" autocomplete="current-password" required></label>
          <label>New password (10+ characters)<input name="next" type="password" autocomplete="new-password" minlength="10" required></label>
          <label>Confirm new password<input name="confirm" type="password" autocomplete="new-password" minlength="10" required></label>
          <div class="full row-actions"><button class="btn primary" type="submit">Save password</button><small class="muted">Signs you out on other devices.</small></div>
        </form>
      </div>
      <div class="card"><h3 style="margin-top:0">What you can do</h3>${p.can_do.map((c) => `<span class="pill" style="margin:0 .2rem .3rem 0;display:inline-block">${esc(c)}</span>`).join("")}</div>
    </div>
    <div class="card" style="margin-top:1rem"><h3 style="margin-top:0">Your recent activity</h3>${p.recent.length ? `<div class="act-list">${p.recent.map((t) => `<div class="act-item"><strong>${esc(t.what)}</strong>${t.target ? ` · ${esc(t.target)}` : ""}<small>${esc(fmt(t.at))}</small></div>`).join("")}</div>` : `<p class="muted">Nothing yet.</p>`}</div>`;
  $("pwBtn").onclick = () => $("pwForm").classList.toggle("hidden");
  $("replayJourney").onclick = startTeamJourney;
  $("pwForm").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    if (fd.get("next") !== fd.get("confirm")) return toast("The new passwords do not match");
    try {
      await PortalAPI.json("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: fd.get("current"), new_password: fd.get("next") }) });
      toast("Password changed");
      e.target.reset();
      e.target.classList.add("hidden");
    } catch (err) {
      toast(err.message);
    }
  };
}

/* ---------------- Hiring: openings, candidate interest and candidate profiles for a company's founders.
   An Analyst's profile waits for any Admin's (or the Super Admin's) approval before founders see it; an
   Admin's own profile is shown at once. Candidates can register interest through an opening's link. */
let hiringCompany = "";
async function loadHiring() {
  const el = $("tab-hiring");
  let d;
  try {
    d = await PortalAPI.json(`/api/analyst/hiring${hiringCompany ? `?company_id=${hiringCompany}` : ""}`);
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  const coName = (id) => (d.companies.find((c) => c.id === id) || {}).name || "";
  const openRoles = d.roles.filter((r) => r.status === "open");
  const roleOptions = (cid, selected) => `<option value="">No specific opening</option>` + openRoles.filter((r) => String(r.company_id) === String(cid)).map((r) => `<option value="${r.id}"${r.id === selected ? " selected" : ""}>${esc(r.title)}</option>`).join("");
  const coOptions = (sel) => d.companies.map((c) => `<option value="${c.id}"${String(c.id) === String(sel ?? hiringCompany) ? " selected" : ""}>${esc(c.name)}</option>`).join("");
  const STATUS_CLASS = { featured: "warn", interested: "on", not_fit: "off", withdrawn: "off" };
  const STAFF_LABEL = { featured: "Waiting for the founder", interested: "Founder interested", not_fit: "Not a fit", withdrawn: "Withdrawn" };
  const APPROVAL_PILL = { pending: ["warn", "Waiting for an Admin's approval"], returned: ["off", "Returned for changes"] };
  const pending = d.profiles.filter((p) => p.approval === "pending");
  const newInterest = d.interest.filter((i) => i.status === "new");
  const profileRow = (p) => {
    const ap = APPROVAL_PILL[p.approval];
    const actions = [];
    if (d.can_approve && p.approval === "pending") actions.push(`<button class="btn primary" type="button" data-hr-approve="${p.id}">Approve</button><button class="btn ghost" type="button" data-hr-return="${p.id}">Return</button>`);
    if (p.approval === "returned" && p.status === "featured") actions.push(`<button class="btn primary" type="button" data-hr-fix="${p.id}">Correct and resubmit</button>`);
    if (p.status === "featured") actions.push(`<button class="btn ghost" type="button" data-hr-status="withdrawn" data-hr="${p.id}">Withdraw</button>`);
    if (p.status === "withdrawn") actions.push(`<button class="btn ghost" type="button" data-hr-status="featured" data-hr="${p.id}">Feature again</button>`);
    return `<div class="person"><span>${esc(p.full_name)}${ap ? ` <span class="pill ${ap[0]}">${esc(ap[1])}</span>` : ` <span class="pill ${STATUS_CLASS[p.status] || ""}">${esc(STAFF_LABEL[p.status] || p.status)}</span>`}${p.source === "interest" ? ` <span class="pill">Via interest link</span>` : p.source === "bulk" ? ` <span class="pill">Bulk upload</span>` : ""}
      <small>${esc(p.company_name)}${p.role_title ? ` · ${esc(p.role_title)}` : ""} · ${esc(p.headline)} · featured by ${esc(p.featured_by)} ${fmt(p.featured_at)}${p.reviewed_by ? ` · reviewed by ${esc(p.reviewed_by)}` : ""}${p.review_note ? ` · note: ${esc(p.review_note)}` : ""}${p.responded_by ? ` · reply from ${esc(p.responded_by)} ${fmt(p.responded_at)}` : ""}${p.request_ref ? ` · request ${esc(p.request_ref)}` : ""}${p.founder_note ? ` · founder's note: ${esc(p.founder_note)}` : ""}</small>
      <details><summary class="muted">Profile</summary><p style="margin:.3rem 0">${esc(p.summary)}</p><p style="margin:.3rem 0"><strong>Why they fit:</strong> ${esc(p.fit_note)}</p>${p.profile_url ? `<a href="${esc(p.profile_url)}" target="_blank" rel="noopener noreferrer">Public profile ↗</a>` : ""}</details></span>
      <span class="row-actions">${actions.join("")}</span></div>`;
  };
  el.innerHTML = `
    
    <div class="filters section">
      <label>Company <select id="hr-filter"><option value="">All my companies</option>${coOptions()}</select></label>
      ${d.can_feature ? `<button class="btn primary" type="button" data-hr-new>+ Feature a profile</button><button class="btn ghost" type="button" data-hr-bulk>Bulk upload (CSV or Excel)</button>` : ""}
    </div>
    <div id="hrBulk" class="card hidden" style="margin-bottom:1rem"></div>
    <div id="hrRole" class="card hidden" style="margin-bottom:1rem"><h3 style="margin-top:0">Add an opening for a company</h3>
      <form id="hrRoleForm" class="review-form">
        <label>Company<select name="company_id" required>${coOptions()}</select></label>
        <label>Role<input name="title" required minlength="2" maxlength="120" placeholder="e.g. VP Engineering"></label>
        <label>Seniority<select name="seniority">${d.seniority.map((l) => `<option${l === "Senior" ? " selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
        <label>Location<input name="location" maxlength="120"></label>
        <label class="full">Notes<textarea name="notes" maxlength="600" rows="2"></textarea></label>
        <div class="full review-actions"><button class="btn primary" type="submit">Save opening</button></div>
      </form></div>
    <div id="hrNew" class="card hidden" style="margin-bottom:1rem"><h3 style="margin-top:0" id="hrNewTitle">Feature a candidate profile</h3>
      <form id="hrForm" class="review-form">
        <input type="hidden" name="interest_id">
        <label>Company<select name="company_id" id="hr-co" required>${coOptions()}</select></label>
        <label>For the opening<select name="role_id" id="hr-roles">${roleOptions(hiringCompany || d.companies[0]?.id)}</select></label>
        <label>Candidate name<input name="full_name" required minlength="2" maxlength="120"></label>
        <label>Current role and organisation<input name="headline" required minlength="3" maxlength="160" placeholder="e.g. Director of Engineering, BMS · an EV OEM"></label>
        <label>Years of experience<input name="experience_years" type="number" min="0" max="60"></label>
        <label>Location<input name="location" maxlength="120"></label>
        <label class="full">Background (2–4 lines)<textarea name="summary" required minlength="10" maxlength="1200" rows="3"></textarea></label>
        <label class="full">Why they fit this opening<textarea name="fit_note" required minlength="10" maxlength="600" rows="2"></textarea></label>
        <label class="full">Profile link (optional, https://)<input name="profile_url" type="url" maxlength="300" placeholder="https://www.linkedin.com/in/…"></label>
        <label class="full check"><input type="checkbox" name="consent" required> The candidate has agreed to share their profile with this company</label>
        <div class="full review-actions"><button class="btn primary" type="submit">${d.can_approve ? "Feature on the founder dashboard" : "Send for an Admin's approval"}</button></div>
      </form></div>
    ${d.can_approve ? `<div class="card" style="margin-bottom:1rem"><h3 style="margin-top:0">Waiting for your approval <small class="muted">(${pending.length})</small></h3>${pending.map(profileRow).join("") || `<p class="muted">Nothing waiting. Analysts' candidate profiles appear here before founders see them.</p>`}</div>` : ""}
    <div class="card" style="margin-bottom:1rem"><h3 style="margin-top:0">Candidate interest <small class="muted">(${newInterest.length} new)</small></h3>
      ${d.interest.map((i) => `<div class="person"><span>${esc(i.full_name)} <span class="pill ${i.status === "new" ? "warn" : i.status === "featured" ? "on" : "off"}">${esc({ new: "New", featured: "Featured", declined: "Declined" }[i.status])}</span>
        <small>${esc(i.company_name)} · ${esc(i.role_title)} · ${esc(i.headline)}${i.experience_years != null ? ` · ${i.experience_years} yrs` : ""}${i.location ? ` · ${esc(i.location)}` : ""} · ${esc(i.email)}${i.phone ? ` · ${esc(i.phone)}` : ""} · ${esc(fmt(i.created_at))}${i.handled_by ? ` · by ${esc(i.handled_by)}` : ""}</small>
        ${i.note || i.profile_url ? `<details><summary class="muted">Their note</summary>${i.note ? `<p style="margin:.3rem 0">${esc(i.note)}</p>` : ""}${i.profile_url ? `<a href="${esc(i.profile_url)}" target="_blank" rel="noopener noreferrer">Profile link ↗</a>` : ""}</details>` : ""}</span>
        <span class="row-actions">${i.status === "new" && d.can_feature ? `<button class="btn primary" type="button" data-int-feature="${i.id}">Feature for the founders</button><button class="btn ghost" type="button" data-int-decline="${i.id}">Decline</button>` : ""}</span></div>`).join("") || `<p class="muted">No interest yet. Turn on an opening's interest link below and share it on LinkedIn or by message.</p>`}</div>
    <div class="card" style="margin-bottom:1rem"><h3 style="margin-top:0">Candidate profiles <small class="muted">(${d.profiles.length})</small></h3>
      ${d.profiles.filter((p) => p.approval !== "pending" || !d.can_approve).map(profileRow).join("") || `<p class="muted">No profiles featured yet.</p>`}</div>
    <div class="card"><h3 style="margin-top:0">Openings <small class="muted">(${openRoles.length} open)</small></h3>
      ${d.roles.map((r) => `<div class="person"><span>${esc(r.title)} <span class="pill ${r.status === "open" ? "on" : "off"}">${esc(r.status_label)}</span>${r.interest_count ? ` <span class="pill">${r.interest_count} interested${r.interest_new ? `, ${r.interest_new} new` : ""}</span>` : ""}
        <small>${esc(coName(r.company_id))} · ${esc(r.seniority)}${r.location ? ` · ${esc(r.location)}` : ""} · added by ${esc(r.added_by)}${r.from_fund ? " (Demo Ventures)" : " (founder)"}${r.notes ? ` · ${esc(r.notes)}` : ""}</small>
        ${r.interest_link ? `<small>Interest link: <code style="word-break:break-all">${esc(r.interest_link)}</code></small>` : ""}</span>
        <span class="row-actions">${d.can_feature && r.status === "open" ? (r.interest_link ? `<button class="btn ghost" type="button" data-copy-link="${esc(r.interest_link)}">Copy link</button><a class="btn ghost" href="${esc(r.interest_link)}" target="_blank" rel="noopener noreferrer">Open</a><button class="btn ghost" type="button" data-role-link="${r.id}" data-on="0">Turn link off</button>` : `<button class="btn ghost" type="button" data-role-link="${r.id}" data-on="1">Get interest link</button>`) : ""}
          ${d.can_feature ? (r.status === "open" ? `<button class="btn ghost" type="button" data-role-st="filled" data-role="${r.id}">Mark filled</button><button class="btn ghost" type="button" data-role-st="closed" data-role="${r.id}">Close</button>` : `<button class="btn ghost" type="button" data-role-st="open" data-role="${r.id}">Reopen</button>`) : ""}</span></div>`).join("") || `<p class="muted">No openings yet. Founders add them from their Hiring page, or add one here.</p>`}</div>`;
  const call = async (path, method, body, msg) => {
    try { await PortalAPI.json(path, { method, body: JSON.stringify(body) }); toast(msg); await loadHiring(); return true; }
    catch (err) { toast(err.message); return false; }
  };
  $("hr-filter").onchange = (e) => { hiringCompany = e.target.value; loadHiring(); };
  if (d.can_feature) {
    const newBox = $("hrNew"), form = $("hrForm");
    el.querySelector("[data-hr-new]").onclick = () => { form.reset(); form.elements.interest_id.value = ""; $("hrNewTitle").textContent = "Feature a candidate profile"; newBox.classList.toggle("hidden"); };
    el.querySelector("[data-hr-role]")?.addEventListener("click", () => $("hrRole").classList.toggle("hidden"));
    el.querySelector("[data-hr-bulk]").onclick = () => bulkPanel($("hrBulk"), { title: "Upload candidate profiles from a spreadsheet", noun: "profile", template: "/api/analyst/hiring/profiles/bulk-template", endpoint: "/api/analyst/hiring/profiles/bulk", sheetField: "file", withFiles: false, reload: loadHiring });
    $("hr-co").onchange = (e) => { $("hr-roles").innerHTML = roleOptions(e.target.value); };
    $("hrRoleForm").onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      await call("/api/analyst/hiring/roles", "POST", { company_id: Number(fd.get("company_id")), title: fd.get("title"), seniority: fd.get("seniority"), location: fd.get("location"), notes: fd.get("notes") }, "Opening added. The founders see it on their Hiring page.");
    };
    form.onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const years = String(fd.get("experience_years") || "").trim();
      const interest = fd.get("interest_id");
      try {
        const r = await PortalAPI.json("/api/analyst/hiring/profiles", { method: "POST", body: JSON.stringify({
          company_id: Number(fd.get("company_id")), role_id: fd.get("role_id") ? Number(fd.get("role_id")) : null,
          full_name: fd.get("full_name"), headline: fd.get("headline"), experience_years: years ? Number(years) : null,
          location: fd.get("location"), summary: fd.get("summary"), fit_note: fd.get("fit_note"),
          profile_url: fd.get("profile_url"), consent_confirmed: fd.get("consent") === "on", interest_id: interest ? Number(interest) : null }) });
        toast(r.approval === "approved" ? "Profile featured. The founders see it on their dashboard now." : "Sent for approval. Founders see it once an Admin approves it.");
        await loadHiring();
      } catch (err) { toast(err.message); }
    };
    el.querySelectorAll("[data-int-feature]").forEach((b) => (b.onclick = () => {
      const i = d.interest.find((x) => x.id == b.dataset.intFeature);
      form.reset();
      form.elements.interest_id.value = i.id;
      form.elements.company_id.value = i.company_id;
      $("hr-roles").innerHTML = roleOptions(i.company_id, i.role_id);
      form.elements.full_name.value = i.full_name;
      form.elements.headline.value = i.headline;
      form.elements.experience_years.value = i.experience_years ?? "";
      form.elements.location.value = i.location || "";
      form.elements.profile_url.value = i.profile_url || "";
      form.elements.summary.value = i.note || "";
      form.elements.consent.checked = true; // they agreed on the interest form
      $("hrNewTitle").textContent = `Feature ${i.full_name} (from the interest link): add why they fit`;
      newBox.classList.remove("hidden");
      newBox.scrollIntoView({ behavior: "smooth", block: "start" });
      form.elements.fit_note.focus();
    }));
    el.querySelectorAll("[data-int-decline]").forEach((b) => (b.onclick = () => { if (confirm("Decline this candidate? They are not shown to the founders.")) call(`/api/analyst/hiring/interest/${b.dataset.intDecline}/decline`, "POST", {}, "Declined"); }));
    el.querySelectorAll("[data-role-link]").forEach((b) => (b.onclick = () => call(`/api/analyst/hiring/roles/${b.dataset.roleLink}/link`, "POST", { on: b.dataset.on === "1" }, b.dataset.on === "1" ? "Interest link is on. Copy it and share it." : "Interest link turned off")));
    el.querySelectorAll("[data-role-st]").forEach((b) => (b.onclick = () => call(`/api/analyst/hiring/roles/${b.dataset.role}`, "PATCH", { status: b.dataset.roleSt }, { filled: "Marked as filled", closed: "Opening closed", open: "Opening reopened" }[b.dataset.roleSt])));
  }
  el.querySelectorAll("[data-copy-link]").forEach((b) => (b.onclick = async () => { try { await navigator.clipboard.writeText(b.dataset.copyLink); toast("Link copied"); } catch (_) { toast("Copy is blocked: select the link and press Ctrl+C"); } }));
  el.querySelectorAll("[data-hr-approve]").forEach((b) => (b.onclick = () => call(`/api/analyst/hiring/profiles/${b.dataset.hrApprove}/review`, "POST", { action: "approve" }, "Approved. The founders see it on their dashboard now.")));
  el.querySelectorAll("[data-hr-return]").forEach((b) => (b.onclick = async () => {
    const note = await askInline(b, { label: "What should change?", multiline: true, required: true, save: "Return to the analyst" });
    if (note !== null) call(`/api/analyst/hiring/profiles/${b.dataset.hrReturn}/review`, "POST", { action: "return", note }, "Returned with your note");
  }));
  el.querySelectorAll("[data-hr-fix]").forEach((b) => (b.onclick = () => {
    const p = d.profiles.find((x) => x.id == b.dataset.hrFix);
    editForm(b, `Correct ${p.full_name}${p.review_note ? ` (note: ${p.review_note})` : ""}`, `
      <label class="full">Current role and organisation<input name="headline" required minlength="3" maxlength="160" value="${esc(p.headline)}"></label>
      <label class="full">Background<textarea name="summary" required minlength="10" maxlength="1200" rows="3">${esc(p.summary)}</textarea></label>
      <label class="full">Why they fit<textarea name="fit_note" required minlength="10" maxlength="600" rows="2">${esc(p.fit_note)}</textarea></label>`,
      "Resubmit for approval", (fd) => call(`/api/analyst/hiring/profiles/${p.id}`, "PATCH", { headline: fd.get("headline"), summary: fd.get("summary"), fit_note: fd.get("fit_note") }, "Resubmitted. It waits for an Admin's approval."));
  }));
  el.querySelectorAll("[data-hr-status]").forEach((b) => (b.onclick = () => call(`/api/analyst/hiring/profiles/${b.dataset.hr}`, "PATCH", { status: b.dataset.hrStatus }, b.dataset.hrStatus === "withdrawn" ? "Profile withdrawn from the founder dashboard" : "Profile featured again")));
}


/* ---------------- Playbook lessons (LMS; shown to founders inside the Playbook): chapters by phase, lessons, completion per company.
   Admins and the Super Admin write, order and publish; everyone with companies sees completion. */
async function loadCourse() {
  const el = $("tab-course");
  let d;
  try {
    d = await PortalAPI.json("/api/admin/course");
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  window.__courseLessons = Object.fromEntries(d.chapters.flatMap((c) => c.lessons).map((l) => [l.id, l]));
  const edit = d.can_edit;
  const resOptions = (sel) => `<option value="">No template</option>${d.resources.map((r) => `<option value="${esc(r.slug)}"${r.slug === sel ? " selected" : ""}>${esc(r.title)}</option>`).join("")}`;
  const pill = (st) => (st === "published" ? `<span class="pill on">Published</span>` : `<span class="pill warn">Draft (founders do not see it)</span>`);
  let n = 0;
  const chapterHtml = (c) => {
    if (c.status === "published") n += 1;
    return `<div class="card course-chapter" style="margin-bottom:.8rem">
      <div class="person"><span><strong>${c.status === "published" ? `Chapter ${n}: ` : ""}${esc(c.title)}</strong> ${pill(c.status)}<small>${esc(c.summary || "")}</small></span>
        ${edit ? `<span class="row-actions"><button class="btn ghost" type="button" data-ch-move="up" data-ch="${c.id}" title="Move up">↑</button><button class="btn ghost" type="button" data-ch-move="down" data-ch="${c.id}" title="Move down">↓</button><button class="btn ghost" type="button" data-ch-edit="${c.id}">Edit</button><button class="btn ghost" type="button" data-ch-status="${c.status === "published" ? "draft" : "published"}" data-ch="${c.id}">${c.status === "published" ? "Unpublish" : "Publish"}</button><button class="btn ghost" type="button" data-ch-del="${c.id}">Remove</button></span>` : ""}</div>
      <ol class="lesson-admin">${c.lessons.map((l) => `<li><div class="person"><span>${esc(l.title)} ${l.status === "published" ? "" : pill(l.status)}<small>${l.minutes} min${l.resource_slug ? (() => { const res = d.resources.find((r) => r.slug === l.resource_slug); return res ? ` · <button class="text-btn" type="button" data-res-open="${res.id}">${esc(res.title)} ↓</button>` : ` · template: ${esc(l.resource_slug)}`; })() : ""}${l.body ? ` · <button class="text-btn" type="button" data-lesson-read="${l.id}">Read the lesson</button>` : ""}${l.video_url ? " · video" : ""} · done at ${l.companies_done} compan${l.companies_done === 1 ? "y" : "ies"}</small></span>
        ${edit ? `<span class="row-actions"><button class="btn ghost" type="button" data-ls-move="up" data-ls="${l.id}" title="Move up">↑</button><button class="btn ghost" type="button" data-ls-move="down" data-ls="${l.id}" title="Move down">↓</button><button class="btn ghost" type="button" data-ls-edit="${l.id}">Edit</button><button class="btn ghost" type="button" data-ls-status="${l.status === "published" ? "draft" : "published"}" data-ls="${l.id}">${l.status === "published" ? "Unpublish" : "Publish"}</button><button class="btn ghost" type="button" data-ls-del="${l.id}">Remove</button></span>` : ""}</div></li>`).join("") || `<li class="muted" style="list-style:none;margin-left:-1.2rem">No lessons yet.</li>`}</ol>
      ${edit ? `<button class="btn ghost" type="button" data-ls-add="${c.id}">+ Add a lesson</button>` : ""}</div>`;
  };
  el.innerHTML = `
    
    <div class="card section"><h3 style="margin-top:0">Completion by company</h3><div class="scroll"><table class="data"><thead><tr><th>Company</th><th class="num">Lessons done</th><th>Progress</th><th>Last activity</th></tr></thead><tbody>
      ${d.progress.map((p) => `<tr><td>${esc(p.company)}</td><td class="num">${p.done} of ${p.total}</td><td><div class="bar"><span style="width:${p.pct}%"></span></div> ${p.pct}%</td><td>${esc(fmt(p.last))}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">No companies.</td></tr>`}
    </tbody></table></div></div>
    ${Object.entries(d.phases).map(([no, name]) => `<section class="section"><div class="section-title"><h3 style="margin:0">${esc(name)}</h3>${edit ? `<button class="btn ghost" type="button" data-ch-add="${no}">+ Add a chapter</button>` : ""}</div>
      ${d.chapters.filter((c) => String(c.phase_no) === no).map(chapterHtml).join("") || `<p class="muted">No chapters in this phase.</p>`}</section>`).join("")}`;
  if (!edit) return;
  const call = async (path, method, body, msg) => {
    try { await PortalAPI.json(path, { method, body: body ? JSON.stringify(body) : undefined }); toast(msg); await loadCourse(); return true; }
    catch (err) { toast(err.message); return false; }
  };
  const lessonFields = (l = {}) => `
    <label class="full">Lesson title<input name="title" required minlength="3" maxlength="160" value="${esc(l.title || "")}"></label>
    <label>Minutes to read<input name="minutes" type="number" min="1" max="240" value="${l.minutes || 5}" required></label>
    <label>Template from the library<select name="resource_slug">${resOptions(l.resource_slug)}</select></label>
    <label class="full">Text (blank line = new paragraph; start a line with "- " for a bullet)<textarea name="body" required minlength="20" maxlength="8000" rows="8">${esc(l.body || "")}</textarea></label>
    <label class="full">Video link (optional, https://)<input name="video_url" type="url" maxlength="500" value="${esc(l.video_url || "")}"></label>
    <label class="full check"><input type="checkbox" name="publish"${!l.id || l.status === "published" ? " checked" : ""}> Published (founders see it)</label>`;
  const lessonBody = (fd) => ({ title: fd.get("title"), minutes: Number(fd.get("minutes")), resource_slug: fd.get("resource_slug") || null, body: fd.get("body"), video_url: fd.get("video_url") || null, status: fd.get("publish") === "on" ? "published" : "draft" });
  el.querySelectorAll("[data-ch-add]").forEach((b) => (b.onclick = () => editForm(b, `New chapter in ${d.phases[b.dataset.chAdd]}`, `
    <label class="full">Chapter title<input name="title" required minlength="3" maxlength="160"></label>
    <label class="full">One-line summary<input name="summary" maxlength="600"></label>
    <label class="full check"><input type="checkbox" name="publish"> Publish now (otherwise it stays a draft)</label>`, "Add chapter",
    (fd) => call("/api/admin/course/chapters", "POST", { phase_no: Number(b.dataset.chAdd), title: fd.get("title"), summary: fd.get("summary") || null, status: fd.get("publish") === "on" ? "published" : "draft" }, "Chapter added"))));
  el.querySelectorAll("[data-ch-edit]").forEach((b) => (b.onclick = () => {
    const c = d.chapters.find((x) => x.id == b.dataset.chEdit);
    editForm(b, `Edit chapter: ${c.title}`, `
      <label class="full">Chapter title<input name="title" required minlength="3" maxlength="160" value="${esc(c.title)}"></label>
      <label class="full">One-line summary<input name="summary" maxlength="600" value="${esc(c.summary || "")}"></label>
      <label>Phase<select name="phase_no">${Object.entries(d.phases).map(([no, name]) => `<option value="${no}"${String(c.phase_no) === no ? " selected" : ""}>${esc(name)}</option>`).join("")}</select></label>`, "Save chapter",
      (fd) => call(`/api/admin/course/chapters/${c.id}`, "PATCH", { title: fd.get("title"), summary: fd.get("summary") || "", phase_no: Number(fd.get("phase_no")) }, "Chapter saved"));
  }));
  el.querySelectorAll("[data-ch-move]").forEach((b) => (b.onclick = () => call(`/api/admin/course/chapters/${b.dataset.ch}`, "PATCH", { move: b.dataset.chMove }, "Moved")));
  el.querySelectorAll("[data-ch-status]").forEach((b) => (b.onclick = () => call(`/api/admin/course/chapters/${b.dataset.ch}`, "PATCH", { status: b.dataset.chStatus }, b.dataset.chStatus === "published" ? "Chapter published" : "Chapter hidden from founders")));
  el.querySelectorAll("[data-ch-del]").forEach((b) => (b.onclick = () => { if (confirm("Remove this chapter and all its lessons? Founders' progress on them is removed too. To hide it instead, use Unpublish.")) call(`/api/admin/course/chapters/${b.dataset.chDel}`, "DELETE", null, "Chapter removed"); }));
  el.querySelectorAll("[data-ls-add]").forEach((b) => (b.onclick = () => editForm(b, "New lesson", lessonFields(), "Add lesson",
    (fd) => call(`/api/admin/course/chapters/${b.dataset.lsAdd}/lessons`, "POST", lessonBody(fd), "Lesson added"))));
  el.querySelectorAll("[data-ls-edit]").forEach((b) => (b.onclick = () => {
    const l = d.chapters.flatMap((c) => c.lessons).find((x) => x.id == b.dataset.lsEdit);
    editForm(b, `Edit lesson: ${l.title}`, lessonFields(l), "Save lesson", (fd) => call(`/api/admin/course/lessons/${l.id}`, "PATCH", lessonBody(fd), "Lesson saved"));
  }));
  el.querySelectorAll("[data-ls-move]").forEach((b) => (b.onclick = () => call(`/api/admin/course/lessons/${b.dataset.ls}`, "PATCH", { move: b.dataset.lsMove }, "Moved")));
  el.querySelectorAll("[data-ls-status]").forEach((b) => (b.onclick = () => call(`/api/admin/course/lessons/${b.dataset.ls}`, "PATCH", { status: b.dataset.lsStatus }, b.dataset.lsStatus === "published" ? "Lesson published" : "Lesson hidden from founders")));
  el.querySelectorAll("[data-ls-del]").forEach((b) => (b.onclick = () => { if (confirm("Remove this lesson? To hide it instead, use Unpublish.")) call(`/api/admin/course/lessons/${b.dataset.lsDel}`, "DELETE", null, "Lesson removed"); }));
}

/* ---------------- Messages (meeting 23 Oct): send content to founders by email and WhatsApp, with a preview
   first; the outbox of everything prepared or sent; earlier sends. Without SMTP (test mode) emails wait in the
   outbox as "not sent" and each one has WhatsApp, email-app and copy buttons. */
const KIND_LABEL = { resource: "A resource", event: "An event", update: "A sector update", custom: "Your own message" };
const OUT_KIND = { invite: "Invite", reset: "Password reset", request: "Founder request alert", reply: "Reply to founder", distribution: "Sent to founders", hiring: "Hiring", interest: "Candidate interest", otp: "Sign-in code" };
// Messages tab: one-to-one chats with founders (chat.js), and sending one message to many founders.
let msgView = "chat";
async function loadMessages() {
  const tab = $("tab-messages");
  if (!tab.querySelector("#msgChat")) {
    tab.innerHTML = `<div class="tabs msg-tabs" role="tablist"><button class="tab" data-msg-view="chat">Chats</button>${can("content.submit", "news.publish", "events.manage") ? `<button class="tab" data-msg-view="send">Send to many founders</button>` : ""}<button class="tab" data-msg-view="outbox">Sent emails</button></div>
      <div id="msgChat"></div><div id="msgSend"></div>`;
    tab.querySelectorAll("[data-msg-view]").forEach((b) => (b.onclick = () => { msgView = b.dataset.msgView; showMsgView(); }));
    if (window.Chat) Chat.mount($("msgChat"), { intro: "Founders of your companies" });
  }
  showMsgView();
  const el = $("msgSend");
  let status, sendable = null, outbox, history = [];
  const canSend = can("content.submit", "news.publish", "events.manage");
  try {
    [status, outbox] = await Promise.all([PortalAPI.json("/api/admin/email-status"), PortalAPI.json("/api/admin/outbox"), loadAudienceOptions(true)]);
    if (canSend) [sendable, history] = await Promise.all([PortalAPI.json("/api/admin/messages/sendable"), PortalAPI.json("/api/admin/messages/history")]);
  } catch (err) {
    el.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  const test = status.mode === "test";
  el.innerHTML = `
    
    ${canSend ? `<div class="card section msg-send-part"><h3 style="margin-top:0">Send to founders</h3>
      <form id="sendForm" class="review-form">
        <label>What<select name="kind" id="sd-kind">${Object.entries(KIND_LABEL).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
        <label id="sd-item-wrap">Which one<select name="item_id" id="sd-item"></select></label>
        <label class="full">Subject<input name="subject" id="sd-subject" maxlength="200" placeholder="Filled in from the item when you preview; you can change it"></label>
        <label class="full">Message<textarea name="message" id="sd-message" maxlength="4000" rows="5" placeholder="Filled in from the item when you preview; each founder gets it with their own name"></textarea></label>
        ${audiencePicker({}, "Which founders get it")}
        <div class="full review-actions"><button class="btn ghost" type="submit" data-act="preview">Preview recipients and message</button><button class="btn primary" type="button" id="sd-send" disabled>Send</button></div>
      </form><div id="sendPreview" class="hidden"></div></div>` : ""}
    <div class="card section msg-outbox-part"><h3 style="margin-top:0">Sent emails <small class="muted">(${outbox.length})</small></h3><div class="scroll"><table class="data"><thead><tr><th>When</th><th>To</th><th>Message</th><th>Status</th><th></th></tr></thead><tbody>
      ${outbox.map((m) => `<tr><td>${esc(fmt(m.created_at))}</td><td>${esc(m.to_name || "")}<br><small class="muted">${esc(m.to_email)}${m.company ? ` · ${esc(m.company)}` : ""}</small></td><td><span class="pill">${esc(OUT_KIND[m.kind] || m.kind)}</span> ${esc(m.subject)}<details><summary class="muted">Show message</summary><pre class="msg-body">${esc(m.body)}</pre></details></td><td><span class="pill ${m.status === "sent" ? "on" : m.status === "failed" ? "off" : "warn"}">${esc(EMAIL_STATUS[m.status] || m.status)}</span>${m.status === "sent" ? `<br><small class="muted">${esc(fmt(m.sent_at))}</small>` : ""}${m.status === "failed" && m.error ? `<br><small class="muted">${esc(m.error)}</small>` : ""}</td>
        <td><div class="row-actions">${m.status !== "sent" && !test ? `<button class="btn ghost" type="button" data-resend="${m.id}">Send email</button>` : ""}<a class="btn ghost" href="${esc(m.whatsapp_url)}" target="_blank" rel="noopener noreferrer" title="${m.has_phone ? "Opens WhatsApp with this message" : "No phone number: WhatsApp asks which chat"}">WhatsApp</a><a class="btn ghost" href="${esc(m.mailto_url)}">Email app</a><button class="btn ghost" type="button" data-copy-msg="${m.id}">Copy</button></div></td></tr>`).join("") || `<tr><td colspan="5" class="muted">Nothing yet. Invites, password resets, request alerts and messages you send appear here.</td></tr>`}
    </tbody></table></div></div>
    ${canSend ? `<div class="card msg-send-part"><h3 style="margin-top:0">Earlier sends</h3>${history.map((h) => `<div class="person"><span>${esc(h.subject)}<small>${esc(KIND_LABEL[h.kind] || h.kind)} · ${esc(h.audience)} · ${h.recipients} founder${h.recipients === 1 ? "" : "s"} · ${esc(h.sent_by)} · ${esc(fmt(h.at))}</small></span></div>`).join("") || `<p class="muted">No sends yet.</p>`}</div>` : ""}`;
  el.querySelectorAll("[data-copy-msg]").forEach((b) => (b.onclick = async () => {
    const m = outbox.find((x) => x.id == b.dataset.copyMsg);
    try { await navigator.clipboard.writeText(`${m.subject}\n\n${m.body}`); toast("Message copied"); } catch (_) { toast("Copy is blocked in this browser: open “Show message” and select it"); }
  }));
  el.querySelectorAll("[data-resend]").forEach((b) => (b.onclick = async () => {
    b.disabled = true;
    try { const r = await PortalAPI.json(`/api/admin/outbox/${b.dataset.resend}/send`, { method: "POST" }); toast(r.status === "sent" ? "Email sent" : `Not sent: ${r.error || r.status}`); await loadMessages(); }
    catch (err) { toast(err.message); b.disabled = false; }
  }));
  if (!canSend) return;
  const f = $("sendForm");
  wireAudience(f);
  const fillItems = () => {
    const kind = $("sd-kind").value;
    $("sd-item-wrap").classList.toggle("hidden", kind === "custom");
    const items = sendable[kind] || [];
    $("sd-item").innerHTML = items.map((i) => `<option value="${i.id}">${esc(i.title)}${i.starts_at ? ` · ${esc(istLocal(i.starts_at))}` : ""}</option>`).join("") || `<option value="">Nothing published yet</option>`;
    $("sd-subject").value = ""; $("sd-message").value = "";
    $("sd-send").disabled = true;
  };
  $("sd-kind").onchange = fillItems;
  $("sd-item").onchange = () => { $("sd-subject").value = ""; $("sd-message").value = ""; $("sd-send").disabled = true; };
  f.addEventListener("change", (e) => { if (e.target.closest("[data-aud]")) $("sd-send").disabled = true; });
  fillItems();
  const body = () => {
    const fd = new FormData(f);
    const kind = fd.get("kind");
    return { kind, item_id: kind === "custom" ? null : Number(fd.get("item_id")) || null, subject: fd.get("subject") || null, message: fd.get("message") || null, ...readAudience(f) };
  };
  f.onsubmit = async (e) => {
    e.preventDefault();
    if (audienceIncomplete(readAudience(f), f)) { toast("Choose which founders get it"); return; }
    try {
      const pv = await PortalAPI.json("/api/admin/messages/preview", { method: "POST", body: JSON.stringify(body()) });
      $("sd-subject").value = pv.subject; $("sd-message").value = pv.message;
      $("sendPreview").innerHTML = `<div class="msg-preview"><strong>${pv.recipients.length} founder${pv.recipients.length === 1 ? "" : "s"} will get this${pv.email_mode === "test" ? " (test mode: emails wait in the outbox)" : ""}</strong>
        <div class="check-grid">${pv.recipients.map((r) => `<span class="pill">${esc(r.name)} · ${esc(r.company)}</span>`).join("") || `<span class="muted">No active founder matches this audience yet. Invite founders first, or choose another audience.</span>`}</div>
        <small class="muted">Example, as the first founder sees it</small><pre class="msg-body">${esc(pv.example)}</pre></div>`;
      $("sendPreview").classList.remove("hidden");
      $("sd-send").disabled = !pv.recipients.length;
    } catch (err) {
      toast(err.message);
    }
  };
  $("sd-send").onclick = async () => {
    if (!confirm("Send this message to every founder in the preview?")) return;
    $("sd-send").disabled = true;
    try {
      const r = await PortalAPI.json("/api/admin/messages/send", { method: "POST", body: JSON.stringify(body()) });
      toast(`${r.sent_to} message${r.sent_to === 1 ? "" : "s"} ${r.email_mode === "test" ? "added to the outbox" : "sent"}`);
      await loadMessages();
      const p = $("secretPanel");
      p.innerHTML = `<strong>${r.sent_to} founder${r.sent_to === 1 ? "" : "s"}${r.email_mode === "test" ? " · test mode: emails wait in the outbox" : " emailed"}</strong><div class="row-actions" style="flex-wrap:wrap;margin-top:.4rem">${r.recipients.map((x) => `<a class="btn ghost" href="${esc(x.whatsapp_url)}" target="_blank" rel="noopener noreferrer">WhatsApp ${esc(x.name)}${x.has_phone ? "" : " (no phone)"}</a>`).join("")}</div><div><button class="btn ghost" type="button" id="hideSecret">Done</button></div>`;
      p.classList.remove("hidden");
      $("hideSecret").onclick = () => { p.classList.add("hidden"); p.innerHTML = ""; };
      p.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      toast(err.message);
      $("sd-send").disabled = false;
    }
  };
}

/* ---------------- Access: what this signed-in person may see (the server checks every request too) */
// Mirrors WORKSPACE_TABS in backend/permissions.py: a section shows if the user holds any listed permission.
const TAB_PERMS = {
  overview: ["overview.view"], approvals: ["content.approve"], companies: ["companies.view"], queue: ["requests.handle"],
  intakes: ["intakes.view"], activity: ["activity.founders", "activity.analysts", "activity.admins"],
  content: ["content.submit", "content.approve"], updates: ["news.publish"], events: ["events.manage"],
  connect: ["connect.manage"], hiring: ["talent.feature", "talent.approve"], messages: ["overview.view"], course: ["lms.manage", "companies.view"], team: ["staff.manage", "admins.manage", "super_admin.handover"], audit: ["audit.view"], profile: [],
};
function can(...perms) {
  const granted = me?.permissions || [];
  return perms.some((p) => granted.includes(p));
}
function allowedTabs() {
  return Object.keys(TAB_PERMS).filter((t) => !TAB_PERMS[t].length || can(...TAB_PERMS[t]));
}
function tierCode() {
  const r = me?.roles || [];
  return r.includes("super_admin") ? "super_admin" : r.includes("admin") ? "admin" : "analyst";
}

/* ---------------- User journey: a short walkthrough of the sections this person uses (at most 10 steps).
   Each step opens a section and highlights the control to use there. No tier talk: the sidebar already
   shows only what the person can use (partner review, 4 Nov 2026). */
function teamJourneySteps() {
  const first = (me?.full_name || "").split(" ")[0];
  const tier = tierCode();
  const step = (tab, target, title, text, demo, snippet) => ({ title, text, demo, target, snippet, go: () => switchTab(tab) });
  const S = {
    welcome: step(allowedTabs()[0], "#sidebar nav", `Welcome${first ? ", " + first : ""}`,
      "This is the Demo Ventures workspace. The sidebar lists the sections you use: your companies, founder requests, content and the network.",
      "Pick any section in the sidebar to open it."),
    overview: step("overview", "#tab-overview .stat-grid", "Overview", "Your companies at a glance. Each number opens its list.", "Click Open founder requests to see what needs an answer.",
      [{ stats: [["2", "Open founder requests"], ["6", "Portfolio companies"], ["41", "Downloads, 30 days"]] }]),
    approvals: step("approvals", "#tab-approvals", "Approvals", "Resources, events, Connect profiles and sector updates from the team wait here for you.", "Approve, or return an item with a note.",
      [{ rows: [["Policy brief for Orbit Health", "Sector update · Zoya Khan", "Waiting"]] }, { buttons: ["Approve", "Return"] }]),
    companies: step("companies", "#tab-companies .company, #tab-companies", "Companies & founders", "Open a company to see its founders, Demo Ventures team, playbook and profile. Invite founders from here.", "Use Preview founder portal to see the portal as that company's founders do.",
      [{ rows: [["Orbit Health", "HealthTech · Bengaluru · Fund III", "2 founders"]] }, { buttons: ["Invite founder", "Preview founder portal"] }]),
    queue: step("queue", "#tab-queue .queue-controls, #tab-queue", "Founder requests", "Every request and introduction founders send lands here.", "Set the status and the owner the founder sees, then save.",
      [{ rows: [["Need a CA for GST filings", "Orbit Health · Finance", "New"]] }]),
    content: step("content", "#tab-content .filters, #tab-content", "Resources", tier === "super_admin" ? "Approve new resources and replace files when they change." : "Add resources one at a time or from a spreadsheet. Each goes live once approved.", "Bulk upload (CSV or Excel) gives you the template to fill.",
      [{ rows: [["Investor update template", "Fundraising and Investor Relations · DOCX", "Waiting"]] }]),
    updates: step("updates", "#updateForm, #tab-updates", "Sector updates", "Write a short update from a reliable source and choose which founders see it.", "Fill in the headline, summary and source, then save."),
    events: step("events", "#tab-events", "Events", "Add an event with its date, time and length. Founders RSVP in the portal, or on the organiser's page for external events.", "Add a join link for online sessions."),
    messages: step("messages", "#tab-messages", "Messages", "Chat with founders one to one, share files, and send announcements to many founders at once.", "Pick a founder on the left to open the conversation."),
    connect: step("connect", "#tab-connect", "Connect", "Investors, service partners, peer founders and Demo Ventures advisors founders can ask to meet.", "Search for a profile to edit it."),
    team: step("team", "#tab-team", "Team & access", tier === "super_admin" ? "Add admins and analysts and choose who reports to whom." : "Add analysts for your companies and reset their passwords.", null),
    audit: step("audit", "#tab-audit .subtabs, #tab-audit", "Audit trail", "Every change and every download, with who did it and when.", "Switch between changes and downloads."),
    profile: step("profile", "#tab-profile .profile-card, #tab-profile", "My profile", "Your details and password. You can replay this tour from the User journey button.", null),
  };
  const order = { super_admin: ["welcome", "approvals", "companies", "queue", "content", "events", "messages", "team", "audit", "profile"],
    admin: ["welcome", "overview", "companies", "queue", "content", "events", "messages", "team", "audit", "profile"],
    analyst: ["welcome", "overview", "companies", "queue", "content", "updates", "events", "messages", "connect", "profile"] }[tier];
  const tabs = allowedTabs();
  return order.filter((k) => k === "welcome" || tabs.includes(k)).slice(0, 10).map((k) => S[k]);
}
function startTeamJourney() {
  if (!window.UserJourney || !me) return;
  UserJourney.start(teamJourneySteps(), {
    title: "Workspace tour",
    onEnd: (reason) => {
      switchTab(allowedTabs()[0]);
      toast(reason === "skipped" ? "Walkthrough skipped. Replay it from My profile." : "You are all set. Replay the walkthrough from My profile.");
    },
  });
}
$("journeyBtn").onclick = startTeamJourney;

/* ---------------- Shell */
const LOADERS = { overview: loadOverview, approvals: loadApprovals, companies: loadCompanies, queue: loadQueue, intakes: loadIntakes, activity: loadActivity, content: loadContent, updates: loadUpdates, events: loadEvents, connect: loadConnect, hiring: loadHiring, messages: loadMessages, course: loadCourse, team: loadTeam, audit: loadAudit, profile: loadProfile };
function switchTab(name) {
  const tabs = allowedTabs();
  if (!tabs.includes(name)) name = tabs[0];
  if (!name) return;
  document.querySelectorAll("[data-tab]").forEach((t) => { t.classList.toggle("active", t.dataset.tab === name); t.setAttribute("aria-current", t.dataset.tab === name ? "page" : "false"); });
  Object.keys(LOADERS).forEach((t) => $(`tab-${t}`).classList.toggle("hidden", t !== name));
  if (FS_TABS.includes(name)) setFounderSupport(true);
  const navBtn = document.querySelector(`[data-tab="${name}"] span`);
  $("pageTitle").textContent = navBtn ? navBtn.textContent : name === "profile" ? "My profile" : "";
  document.title = `${$("pageTitle").textContent} · Demo Ventures workspace`;
  closeMenu();
  try { sessionStorage.setItem("frp_team_tab", name); } catch (_) {}
  if (location.hash.slice(1) !== name) history.replaceState(null, "", `#${name}`); // refresh keeps the section
  LOADERS[name]();
}
document.querySelectorAll("[data-tab]").forEach((t) => (t.onclick = () => switchTab(t.dataset.tab)));
// Founder support is a dropdown: its sections stay hidden until it is opened (or one of them is in use).
const FS_TABS = ["queue", "intakes", "activity"];
function setFounderSupport(open) {
  $("tabBar").classList.toggle("fs-closed", !open);
  $("fsToggle").setAttribute("aria-expanded", String(open));
}
$("fsToggle").onclick = () => setFounderSupport($("tabBar").classList.contains("fs-closed"));
setFounderSupport(false);
// The name and avatar at the bottom of the sidebar open My profile.
$("wsProfile").onclick = () => switchTab("profile");
$("wsProfile").onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); switchTab("profile"); } };

async function showApp(user) {
  me = user;
  $("signinNote").classList.add("hidden");
  $("workspace").classList.remove("hidden");
  $("wsName").textContent = user.full_name;
  $("wsRoles").textContent = ROLE_NAMES[tierCode()];
  $("wsAvatar").textContent = user.full_name.split(" ").map((x) => x[0]).join("").slice(0, 2).toUpperCase();
  try {
    const notice = sessionStorage.getItem("frp_ws_notice");
    if (notice) {
      sessionStorage.removeItem("frp_ws_notice");
      $("secretPanel").innerHTML = `<strong>Super Admin handed over</strong><div>${esc(notice)}</div>`;
      $("secretPanel").classList.remove("hidden");
    }
  } catch (_) {}
  $("founderLink").classList.toggle("hidden", !can("founder.preview"));
  const tabs = allowedTabs();
  document.querySelectorAll("[data-tab]").forEach((t) => t.classList.toggle("hidden", !tabs.includes(t.dataset.tab)));
  document.querySelectorAll("#tabBar [data-group]").forEach((label) => {
    let el = label.nextElementSibling, any = false;
    while (el && !el.hasAttribute("data-group")) { if (!el.classList.contains("hidden")) any = true; el = el.nextElementSibling; }
    label.classList.toggle("hidden", !any);
  });
  let start = tabs[0];
  try { start = sessionStorage.getItem("frp_team_tab") || start; } catch (_) {}
  const hash = location.hash.slice(1);
  if (LOADERS[hash]) start = hash;
  switchTab(start);
  if (tabs.includes("content") && start !== "content") loadContentCounts();
  if (tabs.includes("queue") && start !== "queue") loadQueueCount();
  if (tabs.includes("approvals") && start !== "approvals") loadApprovalCount();
  if (window.UserJourney?.takePending()) startTeamJourney();
}

async function loadContentCounts() {
  try { const d = await PortalAPI.json("/api/analyst/resources?status=in_review"); $("reviewCount").textContent = d.counts.in_review || ""; } catch (_) {}
}
async function loadQueueCount() {
  try { const items = await PortalAPI.json("/api/analyst/work-items"); const open = items.filter((i) => i.internal_status !== "resolved").length; $("queueCount").textContent = open || ""; } catch (_) {}
}
async function loadApprovalCount() {
  try { const d = await PortalAPI.json("/api/admin/approvals"); $("approvalCount").textContent = d.items.length || ""; } catch (_) {}
}

// "Preview founder portal" in the header: choose the company first, then its portal opens read-only in a new tab.
$("founderLink").onclick = async () => {
  document.getElementById("previewPick")?.remove();
  let companies;
  try {
    companies = (await PortalAPI.json("/api/admin/companies")).filter((c) => c.status !== "exited");
  } catch (err) {
    return toast(err.message);
  }
  if (!companies.length) return toast("You have no company to preview yet");
  const box = document.createElement("div");
  box.id = "previewPick";
  box.className = "card preview-pick";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-label", "Preview a founder portal");
  box.innerHTML = `<label>Whose portal do you want to see?<select id="previewPickSel">${companies.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></label>
    <div class="row-actions"><button class="btn primary" type="button" data-pick-open>Open preview</button><button class="btn ghost" type="button" data-pick-cancel>Cancel</button></div>`;
  document.querySelector("main header, header")?.after(box);
  box.querySelector("select").focus();
  box.querySelector("[data-pick-cancel]").onclick = () => box.remove();
  box.querySelector("[data-pick-open]").onclick = () => {
    const c = companies.find((x) => String(x.id) === box.querySelector("select").value);
    box.remove();
    if (c) previewCompany(c);
  };
};

// Mobile: the sidebar slides in, as in the founder portal.
function closeMenu() {
  $("sidebar").classList.remove("open");
  $("scrim").classList.remove("open");
}
$("menu").onclick = () => { $("sidebar").classList.add("open"); $("scrim").classList.add("open"); };
$("scrim").onclick = closeMenu;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

["logoutBtn", "signOutTop"].filter((id) => $(id)).forEach((id) => {
  $(id).onclick = async () => {
    $(id).disabled = true;
    await PortalAPI.signOut();
  };
});

window.addEventListener("portal:session-expired", () => {
  try { sessionStorage.setItem("frp_notice", "Your session has ended. Please sign in again."); } catch (_) {}
  window.location.replace("/");
});

// One sign-in page for everyone: this page only opens for a signed-in staff account.
(async () => {
  await PortalAPI.detect();
  if (!PortalAPI.enabled) {
    $("signinNote").textContent = "The portal server is not reachable. Start it (see README: Quick start), then reload.";
    return;
  }
  const user = PortalAPI.token ? await PortalAPI.me() : null;
  if (!user && PortalAPI.offline) {
    $("signinNote").textContent = "The portal server is not responding. Your sign-in is kept; refresh in a moment.";
    return;
  }
  if (!user || user.account_type !== "staff") {
    window.location.replace("/");
    return;
  }
  PortalAPI.setPreviewCompany(null); // back in the workspace: stop previewing
  await showApp(user);
})();


// Playbook tab: staff open a lesson's template or read the lesson itself, as founders see it.
document.addEventListener("click", async (e) => {
  const res = e.target.closest("[data-res-open]");
  if (res) {
    try { toast(`Downloaded ${await PortalAPI.download(`/api/analyst/resources/${res.dataset.resOpen}/download`)}`); } catch (err) { toast(err.message); }
    return;
  }
  const read = e.target.closest("[data-lesson-read]");
  if (!read) return;
  const li = read.closest("li");
  const open = li.querySelector(".lesson-read");
  if (open) { open.remove(); read.textContent = "Read the lesson"; return; }
  const lesson = (window.__courseLessons || {})[read.dataset.lessonRead];
  const box = document.createElement("div");
  box.className = "lesson-read card";
  box.textContent = lesson?.body || "This lesson has no text yet.";
  li.appendChild(box);
  read.textContent = "Close the lesson";
});

function showMsgView() {
  const tab = $("tab-messages");
  tab.querySelectorAll("[data-msg-view]").forEach((b) => b.classList.toggle("active", b.dataset.msgView === msgView));
  $("msgChat").classList.toggle("hidden", msgView !== "chat");
  $("msgSend").classList.toggle("hidden", msgView === "chat");
  $("msgSend").classList.toggle("msg-outbox-only", msgView === "outbox");
}
