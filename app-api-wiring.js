/** Connects the wireframe UI to the portal API when it is served by the API; enforces RBAC from the session. */
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const RESOURCE_ORDER = ["Finance and Compliance", "Fundraising and Investor Relations", "Growth & Sales", "Business Operations", "Product & Tech Strategy", "Market Intelligence", "People & Hiring", "Research and Reports", "Legal", "Compliance"];
Object.assign(helpCategory, { "Finance and Compliance": "Finance or MIS support", "Fundraising and Investor Relations": "Fundraising support", "Growth & Sales": "Customer or business development", "Business Operations": "Technology or operational support", "Product & Tech Strategy": "Technology or operational support", "Market Intelligence": "Customer or business development", "People & Hiring": "Hiring or HR support", "Research and Reports": "Other" });

const apiState = { intake: null, recommended: [], activity: [], dashboard: null, sub: "All" };

function companyName() {
  return PortalAPI.user?.account_type === "staff" ? "your company" : PortalAPI.user?.company_name || "your company";
}

function isFounder(user) {
  return user?.account_type === "founder";
}

function applyPortalRBAC(user) {
  const staff = user?.account_type === "staff";
  document.querySelectorAll(".rbac-admin").forEach((el) => {
    el.classList.toggle("hidden", !staff); // staff previewing the portal get a link back to the workspace
  });
  const nameEl = document.querySelector(".profile strong");
  const coEl = document.querySelector(".profile span");
  const avatar = document.querySelector(".profile .avatar");
  if (nameEl && user?.full_name) nameEl.textContent = user.full_name;
  if (avatar && user?.full_name) avatar.textContent = user.full_name.split(" ").map((x) => x[0]).join("").slice(0, 2).toUpperCase();
  if (coEl) coEl.textContent = user?.company_name || (staff ? "Demo Ventures · Preview" : coEl.textContent);
  const logout = document.getElementById("logout");
  if (logout && !document.getElementById("accountBtn")) {
    const b = document.createElement("button");
    b.id = "accountBtn";
    b.type = "button";
    b.setAttribute("aria-label", "Account settings");
    b.title = "Change password";
    b.textContent = "⚙";
    b.onclick = openAccount;
    logout.before(b);
  }
}

function openAccount() {
  modal(
    "Change password",
    `<p class="muted">Signed in as ${esc(PortalAPI.user?.email || "")}. Changing your password signs out your other devices.</p><label>Current password<input name="current" type="password" autocomplete="current-password" required></label><label>New password (at least 10 characters)<input name="next" type="password" autocomplete="new-password" minlength="10" required></label><label>Confirm new password<input name="confirm" type="password" autocomplete="new-password" minlength="10" required></label>`,
    "Update password",
    async (fd) => {
      if (fd.get("next") !== fd.get("confirm")) {
        toast("New passwords do not match");
        return;
      }
      try {
        await PortalAPI.json("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: fd.get("current"), new_password: fd.get("next") }) });
        toast("Password updated");
      } catch (err) {
        toast(err.message || "Could not update password");
      }
    }
  );
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function relTime(iso) {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return fmtDate(iso);
}

async function refreshHelpFromApi() {
  const list = await PortalAPI.listHelp();
  state.requests = list.map((h) => ({
    id: h.public_ref,
    title: h.subject,
    desc: h.context || "",
    category: h.category,
    source: h.resource_title || "",
    status: h.status,
    resolved: h.resolved,
    date: fmtDate(h.created_at),
    owner: h.owner,
  }));
  const badge = document.getElementById("requestBadge");
  if (badge) badge.textContent = state.requests.filter((r) => !r.resolved).length;
}

async function refreshActivity() {
  apiState.activity = await PortalAPI.getActivity();
}

async function syncPortalFromApi() {
  const [dash, res, conn, intake, updates] = await Promise.all([PortalAPI.getDashboard(), PortalAPI.getResources(), PortalAPI.getConnect(), PortalAPI.getIntake(), PortalAPI.getSectorUpdates()]);
  applySectorUpdates(updates || []);
  apiState.dashboard = dash;
  if (dash) state.dashboardMetrics = dash.metrics;
  if (res) {
    resources.splice(
      0,
      resources.length,
      ...res.map((r) => ({
        id: r.id,
        cat: r.category,
        sub: r.subcategory,
        title: r.title,
        desc: r.description,
        type: r.resource_type,
        review: r.review_note,
        owner: r.content_owner,
        reviewedAt: r.reviewed_at,
        downloadable: r.downloadable,
        companySpecific: r.company_specific,
      }))
    );
  }
  if (conn?.length) {
    providers.splice(
      0,
      providers.length,
      ...conn.map((p) => ({
        id: p.id,
        initials: p.display_name.split(" ").map((x) => x[0]).join("").slice(0, 2).toUpperCase(),
        name: p.display_name,
        role: p.role_title,
        org: p.organization,
        skills: p.skills || [],
        why: p.why_relevant,
      }))
    );
  }
  if (intake) {
    apiState.intake = intake.answers;
    apiState.recommended = intake.recommended_ids || [];
  }
  await Promise.all([refreshHelpFromApi(), refreshActivity(), syncEngagement()]);
}

function applySectorUpdates(list) {
  // Staff preview is generic: the previewed company's name in a news note reads "your company".
  const previewName = PortalAPI.user?.account_type === "staff" ? PortalAPI.previewCompany?.()?.name : "";
  const gen = (t) => (previewName && t ? String(t).split(previewName).join("your company") : t);
  list = list.map((u) => ({ ...u, title: gen(u.title), summary: gen(u.summary), why: gen(u.why) }));
  const when = (iso) => {
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
    return days <= 0 ? "Today" : days === 1 ? "Yesterday" : fmtDate(iso);
  };
  const label = (l) => (l || "UPDATE").toUpperCase();
  sectorUpdates.splice(0, sectorUpdates.length, ...list.map((u) => ({ id: u.id, publishedAt: u.published_at, type: label(u.label).charAt(0) + label(u.label).slice(1).toLowerCase(), title: u.title, summary: u.summary || "", date: when(u.published_at), published: when(u.published_at), why: u.why || "", source: u.source || "Demo Ventures", url: u.source_url || "" })));
  dashboardNews.splice(0, dashboardNews.length, ...list.slice(0, 3).map((u) => ({ id: u.id, label: label(u.label), title: u.title, summary: u.summary || "", why: u.why || "", published: when(u.published_at), source: u.source || "Demo Ventures", url: u.source_url || "" })));
  const badge = document.getElementById("updateBadge");
  if (badge) badge.textContent = list.length;
}

// The wireframe hardcodes the pilot company; in API mode every page speaks for the signed-in company.
function brandHtml(html) {
  const co = companyName();
  const sector = (PortalAPI.user && PortalAPI.user.sector) || "";
  const sectorText = !sector || /\b(ev|energy|mobility)\b/i.test(sector) ? "electric mobility and energy" : sector;
  return html
    .replace(/for Nimbus\b(?! Mobility)/g, `for ${esc(co)}`)
    .replace(/Nimbus Mobility/g, esc(co))
    .replace(/NIMBUS MOBILITY/g, esc(co.toUpperCase()))
    .replace(/signals for electric mobility and energy/g, `signals for ${esc(sectorText)}`);
}

/* ------------------------------------------------------------------ Resource Library (API mode) */
function apiResourceCard(r) {
  return `<article class="card resource-card"><span class="tag">${esc(r.cat.toUpperCase())}${r.sub ? " · " + esc(r.sub.toUpperCase()) : ""} · ${esc(r.type)}</span>${r.companySpecific ? `<span class="audience">Published for ${esc(companyName())}</span>` : ""}<h3>${esc(r.title)}</h3><p>${esc(r.desc)}</p><div class="card-actions">${r.downloadable ? `<button class="btn primary" data-action="download" data-id="${r.id}">${svg("download")} Download</button>` : `<span class="muted">File coming soon</span>`}<button class="btn ghost" data-action="resource-detail" data-id="${r.id}">View details</button></div></article>`;
}

function intakePanel() {
  if (!apiState.intake) {
    return `<section class="card intake-cta"><div><span class="eyebrow">PERSONALISE</span><h2>Get resources picked for ${esc(companyName())}</h2><p class="muted">Answer three short questions. We'll recommend templates for your stage, and your Demo Ventures team sees your priorities.</p></div><button class="btn primary" data-action="intake-start">Start</button></section>`;
  }
  const recs = apiState.recommended.map((id) => resources.find((r) => r.id === id)).filter(Boolean);
  if (apiState.hideRecs) return `<div class="recs-off"><span class="muted">Recommendations are hidden.</span><button class="text-btn" data-show-recs>Show my recommendations</button></div>`;
  return `<section class="section recs"><div class="section-title"><h2>Recommended for ${esc(companyName())}</h2><span class="recs-actions"><button class="text-btn" data-action="intake-start">Change my answers</button><button class="text-btn" data-clear-recs>Clear</button></span></div>${recs.length ? `<div class="grid cols-3">${recs.slice(0, 6).map(apiResourceCard).join("")}</div>` : `<p class="muted">Nothing matches your answers yet. Browse the library below, or ask Demo Ventures.</p>`}</section>`;
}

function apiResourcesPage() {
  const present = new Set(resources.map((r) => r.cat));
  const cats = ["All", ...RESOURCE_ORDER.filter((c) => present.has(c)), ...[...present].filter((c) => !RESOURCE_ORDER.includes(c))];
  if (!cats.includes(state.resourceFilter)) state.resourceFilter = "All";
  let list = state.resourceFilter === "All" ? resources : resources.filter((r) => r.cat === state.resourceFilter);
  const words = (apiState.libQuery || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length) list = list.filter((r) => words.every((w) => [r.title, r.desc, r.cat, r.sub, ...(r.tags || [])].join(" ").toLowerCase().includes(w)));
  const subs = state.resourceFilter === "All" ? [] : ["All", ...new Set(list.map((r) => r.sub).filter(Boolean))];
  if (!subs.includes(apiState.sub)) apiState.sub = "All";
  if (apiState.sub !== "All") list = list.filter((r) => r.sub === apiState.sub);
  const subnav = subs.length > 2 ? `<div class="industry-subsections"><span class="section-label">${esc(state.resourceFilter)} sub-sections</span><div class="subfilters">${subs.map((s) => `<button class="chip ${s === apiState.sub ? "active" : ""}" data-api-sub="${esc(s)}">${esc(s)}</button>`).join("")}</div></div>` : "";
  return (
    head("RESOURCES", "Resource Library", "Templates, checklists and guides for running and growing your company. The Demo Ventures team checks each one before it goes live.", `<button class="btn ghost" data-action="suggest-resource">Can't find something?</button>`) +
    intakePanel() +
    `<div class="page-tools"><label class="connect-search-box"><span aria-hidden="true">${svg("search")}</span><input id="libSearch" type="search" maxlength="80" placeholder="Search resources by name or topic" aria-label="Search resources" value="${esc(apiState.libQuery || "")}" autocomplete="off"></label></div>` +
    `<div class="filters">${cats.map((c) => `<button class="chip ${c === state.resourceFilter ? "active" : ""}" data-filter="${esc(c)}">${esc(c)}</button>`).join("")}</div>${subnav}<div class="grid cols-3" id="libResults">${list.map(apiResourceCard).join("") || `<p class="muted">No resources match. Try another word or topic, or ask Demo Ventures.</p>`}</div>`
  );
}

async function apiDownload(id) {
  const r = resources.find((x) => x.id == id);
  try {
    await PortalAPI.downloadResource(id);
    toast(`${r ? r.title : "Resource"} downloaded`);
    refreshActivity();
  } catch (err) {
    toast(err.message || "Download failed");
  }
}

function apiDetail(r) {
  modal(
    r.title,
    `<span class="tag">${esc(r.cat.toUpperCase())}${r.sub ? " · " + esc(r.sub.toUpperCase()) : ""} · ${esc(r.type)}</span><p>${esc(r.desc)}</p><div class="help-handoff"><div><strong>Need help applying this?</strong><small>Your request is prefilled with this resource and routed to ${esc(companyName())}’s Demo Ventures team.</small></div><button type="button" class="btn ghost" data-action="resource-help" data-id="${r.id}">${svg("send")} Ask Demo Ventures for help</button></div>`,
    r.downloadable ? "Download" : "Close",
    () => r.downloadable && apiDownload(r.id)
  );
}

/* ------------------------------------------------------------------ Founder intake (one question at a time) */
const INTAKE_QUESTIONS = [
  { key: "priorities", q: "What matters most in the next 90 days?", hint: "Choose up to three.", type: "multi", max: 3, options: ["Fundraising", "Sales & GTM", "Product", "Finance & reporting", "Operations & people", "Hiring", "Market & ICP"] },
  { key: "fundraising", q: "Where are you on fundraising?", type: "single", options: ["Not raising in the next 6 months", "Preparing to raise in 3–6 months", "Actively raising now"] },
  { key: "blocker", q: "Anything blocking you that Demo Ventures should know?", hint: "Optional, shared only with your Demo Ventures team.", type: "text" },
];

function openIntake() {
  const answers = { ...(apiState.intake || {}) };
  let step = 0;
  const m = document.getElementById("modal");
  const renderStep = () => {
    const Q = INTAKE_QUESTIONS[step];
    const val = answers[Q.key];
    let field;
    if (Q.type === "text") {
      field = `<textarea name="answer" rows="4" maxlength="1000" placeholder="e.g. We need introductions to enterprise buyers in logistics">${esc(val || "")}</textarea>`;
    } else {
      const inputType = Q.type === "multi" ? "checkbox" : "radio";
      const chosen = Q.type === "multi" ? val || [] : [val];
      field = `<div class="intake-options">${Q.options.map((o) => `<label class="intake-option"><input type="${inputType}" name="answer" value="${esc(o)}" ${chosen.includes(o) ? "checked" : ""}><span>${esc(o)}</span></label>`).join("")}</div>`;
    }
    m.innerHTML = `<div class="modal"><div class="modal-head"><div><span class="eyebrow">QUESTION ${step + 1} OF ${INTAKE_QUESTIONS.length}</span><h2 id="intakeQ">${esc(Q.q)}</h2></div><button class="icon-btn" data-action="close-modal" aria-label="Close">×</button></div><div class="intake-progress" aria-hidden="true"><span style="width:${((step + 1) / INTAKE_QUESTIONS.length) * 100}%"></span></div><form id="intakeForm" class="form"><div class="modal-body"><fieldset class="intake-fieldset" aria-labelledby="intakeQ">${Q.hint ? `<small class="muted">${esc(Q.hint)}</small>` : ""}${field}<small class="muted intake-error" role="alert"></small></fieldset></div><div class="modal-foot">${Q.type === "text" ? "" : `<button type="button" class="text-btn intake-clear" data-intake-clear>Clear choices</button>`}<button type="button" class="btn ghost" data-intake-back ${step === 0 ? "disabled" : ""}>Back</button><button type="submit" class="btn primary">${step === INTAKE_QUESTIONS.length - 1 ? "See my recommendations" : "Next →"}</button></div></form></div>`;
    m.classList.remove("hidden");
    const form = document.getElementById("intakeForm");
    const first = form.querySelector("input,textarea");
    if (first) first.focus();
    form.querySelectorAll('input[type="checkbox"]').forEach((cb) =>
      cb.addEventListener("change", () => {
        const checked = form.querySelectorAll('input[type="checkbox"]:checked');
        if (Q.max && checked.length > Q.max) {
          cb.checked = false;
          form.querySelector(".intake-error").textContent = `Choose up to ${Q.max}.`;
        }
      })
    );
    const clear = form.querySelector("[data-intake-clear]");
    if (clear) clear.onclick = () => {
      form.querySelectorAll('input[name="answer"]').forEach((i) => { i.checked = false; });
      delete answers[Q.key];
      form.querySelector(".intake-error").textContent = "";
    };
    form.querySelector("[data-intake-back]").onclick = () => {
      step = Math.max(0, step - 1);
      renderStep();
    };
    form.onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      if (Q.type === "multi") answers[Q.key] = fd.getAll("answer");
      else answers[Q.key] = (fd.get("answer") || "").toString().trim() || null;
      if (Q.type !== "text" && (!answers[Q.key] || (Array.isArray(answers[Q.key]) && !answers[Q.key].length))) {
        form.querySelector(".intake-error").textContent = "Please choose an option to continue.";
        return;
      }
      if (step < INTAKE_QUESTIONS.length - 1) {
        step += 1;
        renderStep();
        return;
      }
      try {
        const res = await PortalAPI.submitIntake(answers);
        apiState.intake = res.answers;
        apiState.recommended = res.recommended_ids || [];
        m.classList.add("hidden");
        toast("Thanks, your library is personalised");
        refreshActivity();
        render("resources");
      } catch (err) {
        form.querySelector(".intake-error").textContent = err.message || "Could not save, try again.";
      }
    };
  };
  renderStep();
}

/* ------------------------------------------------------------------ Dashboard (API mode) */
function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "GOOD MORNING" : h < 17 ? "GOOD AFTERNOON" : "GOOD EVENING";
}

function patchDashboard() {
  const root = document.getElementById("content");
  if (!root || state.page !== "dashboard") return;
  const first = (PortalAPI.user?.full_name || "").split(" ")[0];
  const eyebrow = root.querySelector(".page-head .eyebrow");
  if (eyebrow) eyebrow.textContent = companyName().toUpperCase();
  const logo = apiState.dashboard?.company_logo || "";
  const headText = eyebrow?.parentElement;
  if (headText && /^data:image\/(png|jpeg|webp);base64,/.test(logo) && !headText.querySelector(".dash-logo")) {
    const img = document.createElement("img");
    img.className = "dash-logo";
    img.src = logo;
    img.alt = `${companyName()} logo`;
    headText.prepend(img);
  }
  const title = root.querySelector(".page-head h1");
  if (title) title.textContent = `${greeting().charAt(0)}${greeting().slice(1).toLowerCase()}${first ? ", " + first : ""}`;
  const sub = root.querySelector(".page-head p");
  if (sub) sub.textContent = "Your news, playbook, events and requests with Demo Ventures.";
  const notice = root.querySelector(".section .notice");
  const spot = apiState.dashboard?.company_resource;
  if (notice) {
    notice.innerHTML = spot
      ? `<strong>Published for ${esc(companyName())}:</strong> ${esc(spot.title)} is ready to review. <button class="text-btn" data-action="resource-detail" data-id="${spot.id}">Open resource →</button>`
      : apiState.intake
        ? `<strong>Your library is personalised.</strong> See templates recommended for ${esc(companyName())}. <button class="text-btn" data-goto="resources">Open Resource Library →</button>`
        : `<strong>Personalise your library:</strong> answer three quick questions to get recommended templates. <button class="text-btn" data-action="intake-start">Start →</button>`;
  }
  const quick = root.querySelector(".quick");
  const recs = apiState.recommended.map((id) => resources.find((r) => r.id === id)).filter(Boolean);
  if (quick) quick.innerHTML = (recs.length ? recs : resources).slice(0, 4).map((r) => `<button data-action="resource-detail" data-id="${r.id}">${svg("file")} ${esc(r.title)}</button>`).join("");
  const m = apiState.dashboard?.metrics;
  if (m) {
    root.querySelectorAll(".progress-ring strong").forEach((el) => (el.textContent = `${m.playbook_pct}%`));
    const phase = root.querySelector(".playbook-hero h3");
    if (phase && m.playbook_phase) phase.textContent = m.playbook_phase;
  }
  if (!dashboardNews.length) root.querySelector(".news-flash")?.remove();
  const act = root.querySelector(".activity");
  if (act) {
    const label = { download: "downloaded", help: "", intake: "" };
    act.innerHTML = apiState.activity.length
      ? apiState.activity
          .slice(0, 5)
          .map((a) => `<div class="activity-row"><i class="dot"></i><div><strong>${esc(a.title)}${label[a.kind] ? " " + label[a.kind] : ""}</strong><small>${esc(a.kind === "download" ? a.detail + " resource" : a.detail)}</small></div><time>${esc(relTime(a.at))}</time></div>`)
          .join("")
      : `<p class="muted">No activity yet, open a resource or Ask Demo Ventures to get started.</p>`;
  }
  patchDashboardEngagement(root);
}

/* ------------------------------------------------------------------ Requests (API mode) */
function patchRequestModal() {
  const orig = window.requestModal;
  if (!orig || orig.__apiPatched) return;
  window.requestModal = function (prefill = "", opts = {}) {
    if (!PortalAPI?.enabled) return orig(prefill, opts);
    if (!isFounder(PortalAPI.user)) {
      toast("This is a preview. Founders send requests; the Demo Ventures team answers them in the work queue.");
      return;
    }
    const types = ["Introduction request", "Legal or compliance support", "Finance or MIS support", "Hiring or HR support", "Fundraising support", "Customer or business development", "Technology or operational support", "Resource request", "Other"];
    const src = opts.resource;
    const intro = opts.connectEntry;
    modal(
      "Ask Demo Ventures",
      `${src || intro ? `<div class="request-context"><div><small>Company</small><strong>${esc(companyName())}</strong></div><div><small>${intro ? "Connect profile" : "Originating resource"}</small><strong>${esc(intro ? intro.display_name : src.title)}</strong></div></div>` : ""}<div class="row"><label>Topic<select name="type">${types.map((t) => `<option${t === opts.type ? " selected" : ""}>${t}</option>`).join("")}</select></label></div><label>Subject<input name="subject" value="${esc(prefill)}" maxlength="200" required></label><label>How can we help?<textarea name="context" maxlength="4000" required>${esc(opts.context || "")}</textarea></label><small class="muted">Your message goes to your Demo Ventures team, not a public ticket queue.</small>`,
      "Send to Demo Ventures",
      async (fd) => {
        try {
          const res = await PortalAPI.submitHelp({ subject: fd.get("subject"), context: fd.get("context"), category: fd.get("type"), resource_id: src ? src.id : null, connect_entry_id: intro ? intro.id : null });
          await Promise.all([refreshHelpFromApi(), refreshActivity()]);
          toast(`Sent · reference ${res.public_ref}`);
          render("requests");
        } catch (err) {
          toast(err.message || "Could not send, check API connection");
        }
      }
    );
  };
  window.requestModal.__apiPatched = true;
}

function requestDetail(r) {
  modal(
    r.title,
    `<span class="status ${r.resolved ? "resolved" : "progress"}">${esc(r.status)}</span><p>${esc(r.desc)}</p>${r.source ? `<p class="muted"><strong>Related to:</strong> ${esc(r.source)}${r.category ? ` · ${esc(r.category)}` : ""}</p>` : ""}<div class="detail-grid"><div><small>Reference</small><strong>${esc(r.id)}</strong></div><div><small>Demo Ventures contact</small><strong>${esc(r.owner)}</strong></div><div><small>Sent</small><strong>${esc(r.date)}</strong></div></div><div class="timeline"><div class="timeline-item"><strong>Message sent</strong><small>${esc(r.date)} · by ${esc(PortalAPI.user?.full_name || "you")}</small></div><div class="timeline-item"><strong>Team routing</strong><small>Demo Ventures gives it to the right person and keeps the status here</small></div></div>`,
    "Send a follow-up",
    () => requestModal(`Follow-up on ${r.id}: ${r.title}`, { type: r.category })
  );
}

function apiResourceHelp(r) {
  requestModal(`Help applying: ${r.title}`, { resource: r, type: helpCategory[r.cat] || "Other", context: `We are working with the ${r.title} (${r.type}) and would like Demo Ventures support to apply it to ${companyName()}. Specifically: ` });
}

function installApiPages() {
  pages.resources = apiResourcesPage;
  window.resourceHelp = apiResourceHelp;
  if (!pages.dashboard.__api) {
    const base = pages.dashboard;
    pages.dashboard = function () {
      queueMicrotask(patchDashboard);
      return base();
    };
    pages.dashboard.__api = true;
  }
  installEngagementPages();
  window.detail = apiDetail;
  // Staff previewing the portal get this page: links into the Demo Ventures workspace (the wireframe version only simulated actions).
  pages.admin = function () {
    return (
      head("DEMO VENTURES TEAM ONLY", "Demo Ventures workspace", "Where the Demo Ventures team runs the portal: companies, founder requests, content and the network.", `<a class="btn primary" href="/analyst.html#overview">Open the workspace →</a>`) +
      `<div class="grid cols-3">${[
        ["Companies & founders", "Add alpha companies, invite founders with one-time passwords, deactivate or reset accounts.", "companies"],
        ["Demo Ventures team & playbook", "Assign the relationship partner and portfolio analyst (history kept) and manage each company's playbook tasks.", "companies"],
        ["Resources", "Upload resources one by one or from a CSV; the Super Admin approves them at the weekly review.", "content"],
        ["Approvals", "The Super Admin approves everything Admins and Analysts add before founders see it.", "approvals"],
        ["Sector updates", "Write short updates for one company from a reliable source, with automatic expiry.", "updates"],
        ["Founder requests", "Route founder requests and set the owner the founder sees.", "queue"],
        ["Events", "Publish events to all founders or one company, see RSVPs, add recordings.", "events"],
        ["Connect directory", "Add, edit and hide Connect profiles founders can request introductions to.", "connect"],
        ["Team & access", "Super Admin, Admins and Analysts; hand over Super Admin; every change is in the audit trail.", "team"],
      ].map(([h, p, tab]) => `<article class="card resource-card"><span class="tag">WORKSPACE</span><h3>${h}</h3><p>${p}</p><div class="card-actions" style="margin-top:auto;padding-top:12px"><a class="btn ghost" href="/analyst.html#${tab}">Open →</a></div></article>`).join("")}</div>`
    );
  };
  Object.keys(pages).forEach((k) => {
    if (pages[k].__branded) return;
    const base = pages[k];
    pages[k] = function () {
      return brandHtml(base());
    };
    pages[k].__branded = true;
  });
}

// Capture phase: runs before the wireframe's simulated handlers and replaces them in API mode.
document.addEventListener(
  "click",
  (e) => {
    if (!PortalAPI.enabled || !PortalAPI.user) return;
    const el = e.target.closest('[data-action="download"],[data-action="intake-start"],[data-api-sub],[data-action="request-detail"],[data-filter]');
    if (!el) return;
    if (el.dataset.filter) {
      apiState.sub = "All";
      return; // wireframe handler applies the category filter
    }
    e.stopImmediatePropagation();
    e.preventDefault();
    if (el.dataset.apiSub) {
      apiState.sub = el.dataset.apiSub;
      render("resources");
    } else if (el.dataset.action === "download") apiDownload(el.dataset.id);
    else if (el.dataset.action === "intake-start") openIntake();
    else if (el.dataset.action === "request-detail") requestDetail(state.requests[el.dataset.id]);
  },
  true
);

window.addEventListener("portal:session-expired", () => {
  try { sessionStorage.setItem("frp_notice", "Your session has ended. Please sign in again."); } catch (_) {}
  window.location.replace("/");
});

/** Both Sign out buttons end the server session and reload to a clean sign-in page. */
function patchLogout() {
  ["logout", "signOutBtn"].forEach((id) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.onclick = async (e) => {
      e.preventDefault();
      btn.disabled = true;
      if (PortalAPI.enabled) await PortalAPI.signOut();
      else {
        document.getElementById("app").classList.add("hidden");
        document.getElementById("login").classList.remove("hidden");
      }
    };
  });
}

/* ------------------------------------------------------------------ Page in the address (#events) */
const PORTAL_PAGES = ["dashboard", "resources", "updates", "connect", "requests", "playbooks", "events", "admin"];
function pageFromHash() {
  const h = window.location.hash.slice(1);
  if (!PORTAL_PAGES.includes(h)) return "dashboard";
  if (h === "admin" && isFounder(PortalAPI.user)) return "dashboard";
  return h;
}
(function rememberPage() {
  const orig = window.render;
  if (!orig || orig.__hashAware) return;
  const wrapped = function (page) {
    const result = orig.apply(this, arguments);
    const current = typeof page === "string" ? page : state.page;
    // Each page change gets its own history entry, so refresh keeps the page and Back works.
    if (PortalAPI.enabled && PortalAPI.user && current && window.location.hash.slice(1) !== current && !wrapped.restoring) {
      history.pushState(null, "", `#${current}`);
    }
    return result;
  };
  wrapped.__hashAware = true;
  window.render = wrapped;
  window.addEventListener("popstate", () => {
    if (!PortalAPI.user || document.getElementById("app").classList.contains("hidden")) return;
    wrapped.restoring = true;
    try { window.render(pageFromHash()); } finally { wrapped.restoring = false; }
  });
})();

function finishRestoring() {
  document.documentElement.classList.remove("restoring");
}

function showLoginError(msg) {
  const el = document.getElementById("loginError");
  if (!el) return;
  el.textContent = msg;
  el.hidden = !msg;
}

async function enterFounderApp(user) {
  applyPortalRBAC(user);
  installApiPages();
  await syncPortalFromApi();
  document.getElementById("login").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  render(pageFromHash());
  finishRestoring();
  if (isFounder(user) && window.UserJourney?.takePending()) startFounderJourney();
}

async function tryRestoreSession() {
  if (!PortalAPI.enabled || !PortalAPI.token) return finishRestoring();
  const user = await PortalAPI.me();
  if (!user) {
    finishRestoring();
    if (PortalAPI.offline) showLoginError("The portal server is not responding. Your sign-in is kept; refresh in a moment.");
    return;
  }
  PortalAPI.user = user;
  // Staff land in the workspace; those allowed to preview the founder portal may stay here.
  if (!isFounder(user) && !(user.permissions || []).includes("founder.preview")) {
    window.location.replace("analyst.html");
    return;
  }
  await enterFounderApp(user);
}

document.addEventListener("DOMContentLoaded", () => {
  patchLogout();
  try {
    const notice = sessionStorage.getItem("frp_notice");
    if (notice) {
      sessionStorage.removeItem("frp_notice");
      showLoginError(notice);
    }
  } catch (_) {}
  setTimeout(finishRestoring, 8000); // never leave the page blank if the server hangs
  PortalAPI.detect().then(async () => {
    patchRequestModal();
    const hint = document.querySelector("#loginForm > small");
    if (PortalAPI.enabled && ["production", "replica"].includes(PortalAPI.health?.environment) && hint) hint.remove();
    if (!PortalAPI.enabled && PortalAPI.token) {
      finishRestoring();
      showLoginError("The portal server is not responding. Your sign-in is kept; refresh in a moment.");
      return;
    }
    await tryRestoreSession();
  });

  const form = document.getElementById("loginForm");
  if (!form || form.__apiLogin) return;
  form.__apiLogin = true;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    await PortalAPI.detect();
    if (PortalAPI.enabled) {
      showLoginError("");
      const btn = form.querySelector('button[type="submit"]');
      btn.disabled = true;
      try {
        const email = document.getElementById("email").value;
        const password = form.querySelector('input[type="password"]').value;
        const data = await PortalAPI.login(email, password);
        PortalAPI.user = data.user;
        if (window.location.hash) history.replaceState(null, "", "/"); // a fresh sign-in starts on the dashboard
        window.UserJourney?.markPending(); // every sign-in opens the user journey on the next screen
        // One sign-in page for everyone: the server says where this account lands.
        if (!isFounder(data.user)) {
          window.location.replace(data.redirect || "analyst.html");
          return;
        }
        await enterFounderApp(data.user);
      } catch (err) {
        await PortalAPI.logout();
        showLoginError(err.message || "Login failed");
      } finally {
        btn.disabled = false;
      }
      return;
    }
    // Without the server there is nothing to sign in to: never open the sample wireframe.
    showLoginError(PortalAPI.health && PortalAPI.health.status !== "ok"
      ? "The portal database is unavailable. Please try again shortly."
      : "The portal server is not reachable. Start it (see README: Quick start), then try again.");
  });
});

// Phones: the header search is an icon; tapping it opens the full-width search box.
(() => {
  const box = document.querySelector("header .search");
  const input = document.getElementById("globalSearch");
  if (!box || !input) return;
  box.addEventListener("click", () => input.focus());
  input.addEventListener("keydown", (e) => { if (e.key === "Escape") input.blur(); });
})();


// Resource Library: the search box filters as you type (the page keeps focus); recommendations can be cleared.
document.addEventListener("input", (e) => {
  if (e.target.id !== "libSearch") return;
  apiState.libQuery = e.target.value.trim();
  const pos = e.target.selectionStart;
  render("resources");
  const box = document.getElementById("libSearch");
  if (box) { box.focus(); box.setSelectionRange(pos, pos); }
});
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-clear-recs]")) { apiState.hideRecs = true; render("resources"); }
  else if (e.target.closest("[data-show-recs]")) { apiState.hideRecs = false; render("resources"); }
});
