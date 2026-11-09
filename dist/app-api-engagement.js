/** API-backed Events (RSVP + calendar), 100-Day Playbook tasks, Connect directory and notifications.
 *  Loaded after phase1-features.js; activated by installApiPages() in app-api-wiring.js. */
const engagement = { events: [], eventsTab: "Upcoming", playbook: null, pbView: "tasks", connect: [], notifications: { items: [], unread: 0 }, openPhase: null };
const CONNECT_GROUPS = ["Operational Support Network", "Peer Founder Network", "Investor & Fundraising Ecosystem", "Demo Ventures Network"];
const IST = { timeZone: "Asia/Kolkata" };

function istDate(iso, opts) {
  return new Date(iso).toLocaleString("en-IN", { ...IST, ...opts });
}

async function syncEngagement() {
  const [events, playbook, connect, notes] = await Promise.all([
    PortalAPI.json("/api/founder/events").catch(() => []),
    PortalAPI.json("/api/founder/playbook").catch(() => null),
    PortalAPI.json("/api/founder/connect").catch(() => []),
    PortalAPI.json("/api/founder/notifications").catch(() => ({ items: [], unread: 0 })),
  ]);
  engagement.events = events;
  engagement.playbook = playbook;
  engagement.connect = connect;
  engagement.notifications = notes;
  renderNotificationDrawer();
}

/* ------------------------------------------------------------------ Notifications */
const NOTE_STYLE = { request: ["blue", "send"], update: ["red", "news"], resource: ["gold", "file"], event: ["green", "calendar"] };

function renderNotificationDrawer() {
  const panel = document.getElementById("notificationPanel");
  if (!panel) return;
  panel.querySelectorAll(".notification-item, .notification-empty").forEach((n) => n.remove());
  const foot = panel.querySelector(".drawer-footer");
  const items = engagement.notifications.items || [];
  if (!items.length) {
    const p = document.createElement("p");
    p.className = "muted notification-empty";
    p.style.padding = "0 20px";
    p.textContent = "Nothing new. Updates from Demo Ventures, sector briefs and invitations appear here.";
    panel.insertBefore(p, foot);
  }
  items.forEach((i) => {
    const [cls, icon] = NOTE_STYLE[i.kind] || ["blue", "bell"];
    const b = document.createElement("button");
    b.className = `notification-item${i.read ? "" : " unread"}`;
    b.dataset.goto = i.goto;
    b.dataset.noteKey = i.key;
    b.innerHTML = `<span class="n-icon ${cls}">${svg(icon)}</span><span><strong>${esc(i.title)}</strong><small>${esc(i.text)}</small></span>`;
    panel.insertBefore(b, foot);
  });
  const count = document.querySelector("#notifyBtn span");
  if (count) {
    count.textContent = engagement.notifications.unread;
    count.hidden = !engagement.notifications.unread;
  }
}

async function markRead(keys, all = false) {
  try {
    await PortalAPI.json("/api/founder/notifications/read", { method: "POST", body: JSON.stringify(all ? { all: true } : { keys }) });
    engagement.notifications = await PortalAPI.json("/api/founder/notifications");
    renderNotificationDrawer();
  } catch (_) {
    /* read state is a convenience; never block navigation */
  }
}

/* ------------------------------------------------------------------ Events */
// The date badge carries the day and the start time, so the time never wraps next to the location.
// A multi-day event shows its date range.
function eventDateBadge(e) {
  const month = istDate(e.starts_at, { month: "short" }).toUpperCase();
  const day = istDate(e.starts_at, { day: "numeric" });
  const endDay = e.ends_at ? istDate(e.ends_at, { day: "numeric" }) : day;
  const endMonth = e.ends_at ? istDate(e.ends_at, { month: "short" }).toUpperCase() : month;
  // A range only for programmes of 12 hours or more, so an evening session that ends after midnight stays one day.
  const multi = e.ends_at && (endDay !== day || endMonth !== month) && new Date(e.ends_at) - new Date(e.starts_at) >= 12 * 3600000;
  const time = istDate(e.starts_at, { hour: "numeric", minute: "2-digit" }).replace(" ", "\u00a0");
  return `<div class="event-date${multi ? " multi" : ""}"><span>${esc(month)}</span><strong>${esc(multi ? `${day}–${endMonth !== month ? endMonth.slice(0, 3) + " " : ""}${endDay}` : day)}</strong><small>${esc(time)}</small></div>`;
}

function eventWhen(e) {
  const start = istDate(e.starts_at, { weekday: "short", day: "numeric", month: "short" });
  const from = istDate(e.starts_at, { hour: "numeric", minute: "2-digit" });
  if (!e.ends_at) return `${start}, ${from} IST`;
  const sameDay = istDate(e.ends_at, { day: "numeric", month: "short" }) === istDate(e.starts_at, { day: "numeric", month: "short" });
  return sameDay
    ? `${start}, ${from} to ${istDate(e.ends_at, { hour: "numeric", minute: "2-digit" })} IST`
    : `${start}, ${from} to ${istDate(e.ends_at, { weekday: "short", day: "numeric", month: "short" })}, ${istDate(e.ends_at, { hour: "numeric", minute: "2-digit" })} IST`;
}

function eventAction(e, compact = false) {
  if (e.past) return `<span class="muted">Ended</span>`;
  if (PortalAPI.user?.account_type !== "founder") return `<span class="muted">Founders RSVP here</span>`;
  if (e.rsvp_url) return `<a class="btn primary" href="${esc(e.rsvp_url)}" target="_blank" rel="noopener noreferrer">RSVP ↗</a>`;
  return `<button class="btn ${e.going ? "ghost" : "primary"}" data-api-rsvp="${e.id}" data-going="${e.going ? 1 : 0}">${e.going ? (compact ? "✓ Going" : "✓ Going · Cancel") : "RSVP"}</button>`;
}

function eventCard(e) {
  const where = [e.location, e.join_link || e.meeting_id ? "Online" : ""].filter(Boolean)[0] || "";
  return `<article class="card event-card">${eventDateBadge(e)}<div class="event-body"><h3>${esc(e.title)}</h3><p class="event-meta">${esc(eventWhen(e))}${where ? ` · ${esc(where)}` : ""}</p>${e.description ? `<p>${esc(e.description)}</p>` : ""}<span class="audience">${esc(e.audience)}</span>${e.rsvp_url ? `<small class="muted event-external">External event: you RSVP on the organiser's page.</small>` : ""}</div><div class="event-actions">${eventAction(e)}${e.past ? "" : `<button class="text-btn" data-api-ics="${e.id}">Add to calendar</button>`}</div></article>`;
}

function apiEventsPage() {
  const tabs = ["Upcoming", "My RSVPs", "Past"];
  if (!tabs.includes(engagement.eventsTab)) engagement.eventsTab = "Upcoming";
  const list = engagement.events.filter((e) =>
    engagement.eventsTab === "Upcoming" ? !e.past : engagement.eventsTab === "My RSVPs" ? e.going && !e.past : e.past
  );
  if (engagement.eventsTab === "Past") list.reverse();
  const empty = { Upcoming: "No upcoming events yet. Your invitations will show up here.", "My RSVPs": "You haven't RSVPed to an upcoming event yet.", Past: "No past events yet." }[engagement.eventsTab];
  return (
    head("EVENTS", "Events", "Invitations, office hours and founder programmes. All times are IST.", engagement.events.some((e) => e.going && !e.past) ? `<button class="btn ghost" data-api-ics="mine">Add my RSVPs to calendar</button>` : "") +
    `<div class="tabs">${tabs.map((t) => `<button class="tab ${t === engagement.eventsTab ? "active" : ""}" data-api-events-tab="${t}">${t}</button>`).join("")}</div>` +
    `<section>${list.length ? list.map(eventCard).join("") : `<p class="muted">${empty}</p>`}</section>`
  );
}

async function toggleRsvp(id, going) {
  try {
    await PortalAPI.json(`/api/founder/events/${id}/rsvp`, { method: "POST", body: JSON.stringify({ going }) });
    engagement.events = await PortalAPI.json("/api/founder/events");
    toast(going ? "RSVP confirmed, see you there" : "RSVP cancelled");
    refreshActivity();
    if (state.page === "events" || state.page === "dashboard") render(state.page);
  } catch (err) {
    toast(err.message || "Could not update RSVP");
  }
}

function icsStamp(iso) {
  return new Date(iso).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}

function downloadIcs(events) {
  if (!events.length) return toast("Nothing to add yet");
  const clean = (s) => String(s || "").replace(/[\\,;]/g, (c) => "\\" + c).replace(/\n/g, "\\n");
  const body = events
    .map((e) => ["BEGIN:VEVENT", `UID:fund-event-${e.id}@founder-portal`, `DTSTAMP:${icsStamp(new Date().toISOString())}`, `DTSTART:${icsStamp(e.starts_at)}`, `DTEND:${icsStamp(e.ends_at || e.starts_at)}`, `SUMMARY:${clean(e.title)}`, `LOCATION:${clean(e.location)}`, `DESCRIPTION:${clean(e.description)}`, "END:VEVENT"].join("\r\n"))
    .join("\r\n");
  const ics = `BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Demo Ventures//Founder's Resource Portal//EN\r\nCALSCALE:GREGORIAN\r\n${body}\r\nEND:VCALENDAR\r\n`;
  const url = URL.createObjectURL(new Blob([ics], { type: "text/calendar" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = events.length === 1 ? `${events[0].title.replace(/[^\w -]/g, "")}.ics` : "fund-events.ics";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Calendar file downloaded, open it to add the event");
}

/* ------------------------------------------------------------------ Playbook */
function apiPlaybooksPage() {
  const pb = engagement.playbook;
  const lessonsOn = engagement.pbView === "lessons" && window.PlaybookLessons;
  const tabs = window.PlaybookLessons
    ? `<div class="tabs pb-tabs" role="tablist" aria-label="Playbook views">${[["tasks", "100-day checklist"], ["lessons", "Lessons"]].map(([v, l]) => `<button class="tab ${(lessonsOn ? "lessons" : "tasks") === v ? "active" : ""}" type="button" role="tab" aria-selected="${(lessonsOn ? "lessons" : "tasks") === v}" data-pb-view="${v}">${l}</button>`).join("")}</div>`
    : "";
  if (!pb) {
    return head("PLAYBOOK", "Playbook", "Your company's first 100 days with Demo Ventures, phase by phase, with a short lesson for each step.") + tabs +
      (lessonsOn ? window.PlaybookLessons.section() : `<p class="muted">Your checklist isn't set up yet. The lessons and guides are ready now.</p>` + (window.PlaybookLessons?.guides() || ""));
  }
  const canEdit = PortalAPI.user?.account_type === "founder";
  const active = pb.phases.find((p) => p.status === "active") || pb.phases.find((p) => p.status !== "complete");
  if (engagement.openPhase == null) engagement.openPhase = active ? active.no : 1;
  const linked = [...new Map(pb.phases.flatMap((p) => p.tasks).filter((t) => t.resource_id).map((t) => [t.resource_id, t])).values()];
  return (
    head("PLAYBOOK", "Playbook", "Tick off each task as your team finishes it. Open a phase for its tasks and documents. Your Demo Ventures owner sees the same progress.") +
    `<section class="card playbook-hero"><div><span class="eyebrow">ACTIVE FOR ${esc(companyName().toUpperCase())}</span><h2>${esc(pb.playbook_name)}</h2><p class="muted">Current phase: ${esc(pb.current_phase || "Not started")} · Demo Ventures owner: ${esc(pb.owner_name || "to be assigned")}</p>${lessonsButton(lessonsOn)}</div><div class="progress-ring"><strong>${pb.progress_pct}%</strong></div></section>` +
    tabs +
    (lessonsOn ? window.PlaybookLessons.section() :
    `<section class="section accordion">${pb.phases
      .map((p) => {
        const st = p.status === "complete" ? ["resolved", "Complete"] : p.status === "active" ? ["progress", `Active · ${p.done} of ${p.total} done`] : ["upcoming", "Upcoming"];
        const tasks = p.tasks
          .map((t) => `<div class="task"><label style="display:flex;gap:10px;align-items:center;cursor:${canEdit ? "pointer" : "default"}"><input type="checkbox" data-api-task="${t.id}" ${t.done ? "checked" : ""} ${canEdit ? "" : "disabled"} style="width:18px;height:18px;accent-color:var(--red)"><span>${esc(t.title)}${t.done && t.done_by ? `<small class="muted" style="display:block">Done by ${esc(t.done_by)} · ${esc(fmtDate(t.done_at))}</small>` : ""}</span></label>${t.resource_id ? `<a href="#" data-action="resource-detail" data-id="${t.resource_id}">Open template →</a>` : ""}</div>`)
          .join("");
        return `<div class="phase ${p.no === engagement.openPhase ? "open" : ""}"><button class="phase-head" data-api-phase="${p.no}"><span class="phase-no">${p.no}</span><span><strong>${esc(p.name)}</strong><small>${esc(p.days)}</small></span><span class="status ${st[0]}">${esc(st[1])}</span><span>⌄</span></button><div class="phase-body">${tasks || `<p class="muted">No tasks in this phase yet.</p>`}</div></div>`;
      })
      .join("")}</section>` +
    (window.PlaybookLessons && !lessonsOn ? window.PlaybookLessons.guides() : ""))
  );
}

// Button on the playbook card that opens (or leaves) the Lessons view, with the founder's lesson progress.
function lessonsButton(lessonsOn) {
  if (!window.PlaybookLessons) return "";
  if (lessonsOn) return `<button class="btn ghost pb-lessons-btn" type="button" data-pb-view="tasks">← Back to the 100-day checklist</button>`;
  const d = window.PlaybookLessons.summary();
  if (!d) window.PlaybookLessons.load(); // fills in the lesson count once loaded
  const count = d && d.total ? ` · ${d.done} of ${d.total} done` : "";
  return `<button class="btn primary pb-lessons-btn" type="button" data-pb-view="lessons">${svg("map")} Open the playbook lessons${count}</button>`;
}

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-pb-view]");
  if (!el || state.page !== "playbooks") return;
  engagement.pbView = el.dataset.pbView;
  render("playbooks");
});

async function toggleTask(input) {
  input.disabled = true;
  try {
    const r = await PortalAPI.json(`/api/founder/playbook/tasks/${input.dataset.apiTask}`, { method: "PATCH", body: JSON.stringify({ done: input.checked }) });
    engagement.playbook = await PortalAPI.json("/api/founder/playbook");
    const dash = await PortalAPI.getDashboard();
    if (dash) {
      apiState.dashboard = dash;
      state.dashboardMetrics = dash.metrics;
    }
    refreshActivity();
    toast(input.checked ? `Task completed · playbook ${r.progress_pct}%` : `Task reopened · playbook ${r.progress_pct}%`);
    render("playbooks");
  } catch (err) {
    input.checked = !input.checked;
    input.disabled = false;
    toast(err.message || "Could not update the task");
  }
}

/* ------------------------------------------------------------------ Connect */
// The directory holds Demo Ventures' full connects list (about 1,600 organisations), so the page searches it
// and shows it a page at a time.
const CONNECT_PAGE_SIZE = 24;
let connectQuery = "";
let connectShown = CONNECT_PAGE_SIZE;

function connectInitials(n) {
  return String(n).replace(/\(.*?\)/g, "").split(/\s+/).filter(Boolean).map((x) => x[0]).join("").slice(0, 2).toUpperCase() || "YN";
}

function connectCard(p) {
  const label = p.network_group === "Demo Ventures Network" ? "Request support" : "Request introduction";
  const site = /^https?:\/\//i.test(p.website || "") ? `<a class="connect-site" href="${esc(p.website)}" target="_blank" rel="noopener noreferrer">Website ↗</a>` : "";
  const facts = [
    ["Location", p.organization && p.organization !== "Investor network" && p.organization !== "Demo Ventures operational partner" ? p.organization : ""],
    ["Stage", p.stage],
    ["Cheque size", p.cheque_size],
  ].filter(([, v]) => v);
  const tags = (p.skills || []).filter((t) => t !== p.subcategory);
  return `<article class="card network-card"><div class="provider-head"><div class="avatar">${esc(connectInitials(p.display_name))}</div><div><h3>${esc(p.display_name)}</h3><p>${esc(p.role_title || "")}</p></div></div>
    <span class="tag">${esc((p.subcategory || "").toUpperCase())}</span>
    ${facts.length ? `<dl class="connect-facts">${facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}
    ${tags.length ? `<div class="skills" aria-label="Sectors">${tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div>` : ""}
    ${p.why_relevant ? `<p class="connect-note">${esc(p.why_relevant)}</p>` : ""}
    <div class="network-card-foot">${site ? `<small>${site}</small>` : ""}<button class="btn primary wide" data-api-intro="${p.id}">${svg("send")} ${label}</button></div></article>`;
}

// Sections in the order founders reach for them; within a section the fullest profiles come first.
const CONNECT_SECTION_ORDER = ["Venture Capital", "Deep Tech VCs", "Micro VCs", "Corporate VCs", "International Investors", "Debt Funds", "Secondary Funds", "Investment Bankers", "M&A Advisors", "Exit & Corp Dev Network"];
function connectRank(c) {
  const i = CONNECT_SECTION_ORDER.indexOf(c.subcategory);
  return i < 0 ? CONNECT_SECTION_ORDER.length : i;
}
function connectRichness(c) {
  return (c.website ? 2 : 0) + (c.organization && c.organization !== "Investor network" ? 2 : 0) + Math.min((c.skills || []).length, 3) + (/^[A-Za-z]/.test(c.display_name) ? 1 : 0);
}
function connectSorted(list) {
  return [...list].sort((a, b) => connectRank(a) - connectRank(b) || connectRichness(b) - connectRichness(a) || a.display_name.localeCompare(b.display_name));
}

function connectMatches() {
  const all = connectSorted(engagement.connect.filter((c) => c.network_group === connectGroup));
  const inSub = connectSub === "All" ? all : all.filter((c) => c.subcategory === connectSub);
  const words = connectQuery.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return inSub;
  return inSub.filter((c) => {
    const text = [c.display_name, c.role_title, c.organization, c.subcategory, c.stage, c.why_relevant, ...(c.skills || [])].join(" ").toLowerCase();
    return words.every((w) => text.includes(w));
  });
}

function connectResults() {
  const list = connectMatches();
  const shown = list.slice(0, connectShown);
  const more = list.length - shown.length;
  const summary = list.length
    ? `Showing ${shown.length} of ${list.length} ${list.length === 1 ? "connect" : "connects"}${connectQuery ? ` for “${esc(connectQuery)}”` : ""}`
    : connectQuery ? `No connects match “${esc(connectQuery)}”. Try another name, sector or city, or ask Demo Ventures to help you choose.` : "No profiles in this section yet.";
  return `<p class="muted connect-count" aria-live="polite">${summary}</p><div class="grid cols-3">${shown.map(connectCard).join("")}</div>${more > 0 ? `<div class="connect-more"><button class="btn ghost" type="button" data-connect-more>Show ${Math.min(more, CONNECT_PAGE_SIZE)} more</button></div>` : ""}`;
}

function apiConnectPage() {
  const present = CONNECT_GROUPS.filter((g) => engagement.connect.some((c) => c.network_group === g));
  if (!present.includes(connectGroup)) connectGroup = present[0] || CONNECT_GROUPS[0];
  const all = engagement.connect.filter((c) => c.network_group === connectGroup);
  const count = {};
  all.forEach((c) => { if (c.subcategory) count[c.subcategory] = (count[c.subcategory] || 0) + 1; });
  const subs = ["All", ...Object.keys(count).sort((a, b) => connectRank({ subcategory: a }) - connectRank({ subcategory: b }))];
  if (!subs.includes(connectSub)) connectSub = "All";
  const chip = (s) => `<button class="chip ${s === connectSub ? "active" : ""}" data-connect-sub="${esc(s)}">${esc(s)} <small>${s === "All" ? all.length : count[s]}</small></button>`;
  return (
    head("NETWORK", "Connect", "Investors, service partners, fellow portfolio founders and Demo Ventures advisors. Ask for an introduction and Demo Ventures makes it for you.", `<button class="btn primary" data-action="connect-help">Help me choose</button>`) +
    (present.length > 1 ? `<div class="connect-group-tabs" role="tablist" aria-label="Connection networks">${present.map((g) => `<button class="connect-group-tab ${g === connectGroup ? "active" : ""}" role="tab" aria-selected="${g === connectGroup}" data-connect-group="${esc(g)}">${esc(g)}</button>`).join("")}</div>` : "") +
    `<div class="connect-search"><label class="connect-search-box"><span aria-hidden="true">${svg("search")}</span><input id="connectSearch" type="search" maxlength="80" placeholder="Search by name, sector, stage or city" aria-label="Search connects" value="${esc(connectQuery)}" autocomplete="off"></label></div>` +
    `<div class="connect-subsection"><label class="connect-cat"><span class="section-label">Category</span><select id="connectCat" aria-label="Category">${subs.map((x) => `<option value="${esc(x)}"${x === connectSub ? " selected" : ""}>${esc(x === "All" ? "All categories" : x)} (${x === "All" ? all.length : count[x]})</option>`).join("")}</select></label></div>` +
    `<div id="connectResults">${connectResults()}</div>`
  );
}

document.addEventListener("change", (e) => {
  if (e.target.id !== "connectCat") return;
  connectSub = e.target.value;
  connectShown = CONNECT_PAGE_SIZE;
  const box = document.getElementById("connectResults");
  if (box) box.innerHTML = connectResults();
});
// Typing in the search box refreshes only the results, so the box keeps focus.
document.addEventListener("input", (e) => {
  if (e.target.id !== "connectSearch") return;
  connectQuery = e.target.value.trim().slice(0, 80);
  connectShown = CONNECT_PAGE_SIZE;
  const box = document.getElementById("connectResults");
  if (box) box.innerHTML = connectResults();
});
document.addEventListener(
  "click",
  (e) => {
    if (e.target.closest("[data-connect-sub],[data-connect-group]")) connectShown = CONNECT_PAGE_SIZE; // a new section starts at page one
    const find = e.target.closest("[data-connect-find]"); // a Connect hit in the header search opens Connect searched for it
    if (find) { connectQuery = find.dataset.connectFind; connectSub = "All"; connectShown = CONNECT_PAGE_SIZE; }
    const more = e.target.closest("[data-connect-more]");
    if (!more) return;
    e.stopImmediatePropagation();
    connectShown += CONNECT_PAGE_SIZE;
    const box = document.getElementById("connectResults");
    if (box) box.innerHTML = connectResults();
  },
  true
);

function requestIntro(id) {
  const p = engagement.connect.find((c) => c.id == id);
  if (!p) return;
  const isTeam = p.network_group === "Demo Ventures Network";
  requestModal(`${isTeam ? "Support from" : "Introduction to"} ${p.display_name}`, {
    type: "Introduction request",
    connectEntry: p,
    context: isTeam ? "" : `We'd like an introduction to ${p.display_name} (${p.role_title}). We want to discuss: `,
  });
}

/* ------------------------------------------------------------------ Dashboard + sector updates */
function patchDashboardEngagement(root) {
  const d = apiState.dashboard;
  const pbText = root.querySelector(".playbook-hero p.muted");
  if (pbText && d?.phase_tasks) pbText.textContent = d.phase_tasks.total ? `${d.phase_tasks.done} of ${d.phase_tasks.total} tasks completed in this phase` : "No tasks yet";
  const upcoming = [...root.querySelectorAll(".card")].find((c) => c.querySelector(".section-title h2")?.textContent === "Upcoming");
  const box = upcoming?.querySelector(".event-card");
  if (box) {
    const e = d?.next_event;
    box.outerHTML = e
      ? (() => {
          const full = engagement.events.find((x) => x.id === e.id) || { ...e, past: false, description: "" };
          return `<div class="event-card">${eventDateBadge(full)}<div class="event-body"><h3>${esc(e.title)}</h3><p class="event-meta">${esc(full.location || e.location || "")}</p><span class="audience">${esc(e.audience)}</span></div>${PortalAPI.user?.account_type === "founder" ? eventAction(full, true) : ""}</div>`;
        })()
      : `<p class="muted">No upcoming events. Invitations will appear here.</p>`;
  }
}

function openUpdate(id, list) {
  const u = list.find((x) => x.id == id);
  if (!u) return;
  const label = u.label || u.type;
  markRead([`update:${id}`]);
  modal(
    u.title,
    `<div class="news-detail-meta"><span class="tag">${esc(String(label).toUpperCase())}</span><span>${esc(u.published || u.date || "")}</span></div><p class="lead">${esc(u.summary)}</p>${u.why ? `<p><strong>Why it matters:</strong> ${esc(u.why)}</p>` : ""}<div class="detail-grid"><div><small>Source</small><strong>${esc(u.source)}</strong></div><div><small>Published</small><strong>${esc(u.published || u.date || "")}</strong></div></div><p class="news-links">${/^https?:\/\//.test(u.url || "") ? `<a class="btn primary" href="${esc(u.url)}" target="_blank" rel="noopener noreferrer">Read the full article at ${esc(u.source)} ↗</a>` : ""}<a class="btn ghost" href="https://news.google.com/search?q=${encodeURIComponent(u.title)}&hl=en-IN&gl=IN&ceid=IN:en" target="_blank" rel="noopener noreferrer">More coverage on Google News ↗</a></p>`,
    "Close",
    () => {}
  );
}

/* ------------------------------------------------------------------ Install + events */
function installEngagementPages() {
  pages.events = apiEventsPage;
  pages.playbooks = apiPlaybooksPage;
  pages.connect = apiConnectPage;
  const baseUpdates = pages.updates;
  if (!baseUpdates.__api) {
    pages.updates = function () {
      // Preferences are not stored in the alpha, so the button is not offered.
      return baseUpdates().replace(/<button class="btn ghost" data-action="update-settings">[^<]*<\/button>/, "");
    };
    pages.updates.__api = true;
  }
}

document.addEventListener(
  "click",
  (e) => {
    if (!PortalAPI.enabled || !PortalAPI.user) return;
    const note = e.target.closest("[data-note-key]");
    if (note) {
      markRead([note.dataset.noteKey]);
      toggleDrawer(false);
      return; // the wireframe handler navigates via data-goto
    }
    const el = e.target.closest("[data-api-rsvp],[data-api-ics],[data-api-events-tab],[data-api-phase],[data-api-intro],[data-action=\"mark-read\"],[data-action=\"rsvp\"],[data-action=\"calendar\"],[data-dashboard-news],[data-action=\"sector-detail\"],[data-action=\"network-intro\"]");
    if (!el) return;
    e.stopImmediatePropagation();
    e.preventDefault();
    if (el.dataset.apiRsvp) toggleRsvp(el.dataset.apiRsvp, el.dataset.going !== "1");
    else if (el.dataset.apiIcs) downloadIcs(el.dataset.apiIcs === "mine" ? engagement.events.filter((x) => x.going && !x.past) : engagement.events.filter((x) => x.id == el.dataset.apiIcs));
    else if (el.dataset.apiEventsTab) {
      engagement.eventsTab = el.dataset.apiEventsTab;
      render("events");
    } else if (el.dataset.apiPhase) {
      engagement.openPhase = engagement.openPhase == el.dataset.apiPhase ? 0 : Number(el.dataset.apiPhase);
      el.parentElement.classList.toggle("open");
    } else if (el.dataset.apiIntro) requestIntro(el.dataset.apiIntro);
    else if (el.dataset.action === "mark-read") {
      markRead([], true);
      toast("All notifications marked as read");
    } else if (el.dataset.action === "rsvp" || el.dataset.action === "calendar") render("events");
    else if (el.dataset.dashboardNews) openUpdate(el.dataset.dashboardNews, dashboardNews);
    else if (el.dataset.action === "sector-detail") openUpdate(el.dataset.id, sectorUpdates);
    else if (el.dataset.action === "network-intro") render("connect");
  },
  true
);

document.addEventListener("change", (e) => {
  const input = e.target.closest("input[data-api-task]");
  if (input && PortalAPI.enabled) toggleTask(input);
});
