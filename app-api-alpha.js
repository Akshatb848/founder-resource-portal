/** Alpha additions on top of the API wiring:
 *  - My profile page for the signed-in founder (journey checklist, team, activity)
 *  - Demo Ventures support: the request form sits on the page, and sent messages appear beside it
 *  - Sector updates: date and topic filters (no automatic suggestions in alpha)
 *  - Events: a Join button or meeting ID when Demo Ventures adds one
 *  - Staff preview: shows which company is being previewed
 *  - An interactive founder walkthrough that spotlights the control for each step */
(function () {
  const alpha = { updSort: "latest", updTopic: "All", updQuery: "", profile: null, at: 0, loading: false };

  /* ---------------- Which company this page speaks for (staff preview uses the chosen company) */
  companyName = function () {
    // Staff previewing a founder portal see the company they chose, so it is clear whose portal this is.
    if (PortalAPI.user?.account_type === "staff") return PortalAPI.previewCompany()?.name || "this company";
    return PortalAPI.user?.company_name || "your company";
  };


  const baseRBAC = applyPortalRBAC;
  applyPortalRBAC = function (user) {
    baseRBAC(user);
    const preview = user?.account_type === "staff" ? PortalAPI.previewCompany() : null;
    const coEl = document.querySelector(".profile span");
    if (preview && coEl) coEl.textContent = `Previewing ${preview.name}`;
    let banner = document.getElementById("previewBanner");
    // Staff preview is read-only: the page shows what the company's founders see, and every founder action is hidden.
    document.documentElement.classList.toggle("preview-mode", user?.account_type === "staff");
    if (user?.account_type === "staff") {
      if (!banner) {
        banner = document.createElement("div");
        banner.id = "previewBanner";
        banner.className = "preview-banner";
        document.querySelector("main header")?.after(banner);
      }
      banner.innerHTML = `<span><strong>Preview · ${esc(preview?.name || "founder portal")}</strong> This is what ${esc(preview?.name || "the company")}'s founders see. Nothing here can be changed from the preview.</span><button class="btn ghost" type="button" data-close-preview>Close preview</button>`;
      banner.querySelector("[data-close-preview]").onclick = () => {
        PortalAPI.setPreviewCompany(null);
        if (window.opener) window.close();
        window.location.href = "/analyst.html#companies";
      };
    } else if (banner) banner.remove();
    // The name and avatar in the sidebar open My profile.
    const who = document.querySelector(".profile > div:not(.avatar)");
    const avatar = document.querySelector(".profile .avatar");
    [who, avatar].forEach((n) => {
      if (!n || n.dataset.profileLink) return;
      n.dataset.profileLink = "1";
      n.setAttribute("role", "button");
      n.setAttribute("tabindex", "0");
      n.title = "My profile";
      n.style.cursor = "pointer";
      n.onclick = () => render("profile");
      n.onkeydown = (e) => { if (e.key === "Enter") render("profile"); };
    });
  };

  if (!PORTAL_PAGES.includes("profile")) PORTAL_PAGES.push("profile");

  /* ---------------- My profile */
  function profilePage() {
    const p = alpha.profile;
    if (!alpha.loading && (!p || Date.now() - alpha.at > 5000)) loadProfile(); // fresh on every visit
    if (!p) return head("YOUR ACCOUNT", "My profile", "Loading…");
    if (p.error) return head("YOUR ACCOUNT", "My profile", esc(p.error));
    const initials = p.full_name.split(" ").map((x) => x[0]).join("").slice(0, 2).toUpperCase();
    const s = p.stats || {};
    const done = (p.journey || []).filter((j) => j.done).length;
    return (
      head("YOUR ACCOUNT", "My profile", "Your details, what you have set up so far, and your Demo Ventures team.", `<button class="btn ghost" data-action="account">Change password</button>`) +
      (p.account_type === "staff" ? `` : "") +
      `<div class="grid cols-2">
        <section class="card"><div class="provider-head"><div class="avatar">${esc(initials)}</div><div><h3>${esc(p.full_name)}</h3><p>${esc(p.email)}</p></div></div>
          <div class="detail-grid" style="margin-top:14px">
            <div><small>Company</small><strong>${esc(p.company?.name || companyName())}</strong></div>
            <div><small>Sector · city</small><strong>${esc([p.company?.sector, p.company?.stage, p.company?.city].filter(Boolean).join(" · ") || "-")}</strong></div>
            <div><small>Demo Ventures fund</small><strong>${esc([p.company?.fund, p.company?.invested ? `invested ${p.company.invested}` : ""].filter(Boolean).join(" · ") || "-")}</strong></div>
            <div><small>Member since</small><strong>${esc(fmtDate(p.member_since) || "-")}</strong></div>
            <div><small>Last sign-in</small><strong>${esc(relTime(p.last_sign_in) || "-")}</strong></div>
            <div><small>Relationship manager</small><strong>${esc(p.team?.relationship_manager || "To be assigned")}</strong></div>
            <div><small>Portfolio analyst</small><strong>${esc(p.team?.analyst || "To be assigned")}</strong></div>
          </div></section>
        <section class="card"><div class="section-title"><h2>Your journey</h2><span class="muted">${done} of ${(p.journey || []).length} done</span></div>
          ${(p.journey || []).map((j) => `<div class="task"><span>${j.done ? svg("check") : svg("clock")} ${esc(j.step)}</span>${j.done ? `<small class="muted">Done</small>` : ""}</div>`).join("")}
          <div class="grid cols-2" style="margin-top:14px;gap:10px">
            ${metric("library", "Downloads", s.downloads ?? 0, "Resources you opened")}
            ${metric("send", "Open messages", s.requests_open ?? 0, `${s.requests_total ?? 0} sent in total`)}
            ${metric("calendar", "Upcoming RSVPs", s.upcoming_events ?? 0, "Events you are going to")}
            ${metric("map", "Playbook", (p.playbook?.progress_pct ?? 0) + "%", p.playbook?.current_phase || "Not started")}
          </div></section>
      </div>
      <section class="card section"><div class="section-title"><h2>Your recent activity</h2></div>
        <div class="activity">${(p.recent || []).map((r) => `<div class="activity-row"><i class="dot"></i><div><strong>${esc(r.what)}</strong><small>${esc(r.target || "")}</small></div><time>${esc(relTime(r.at))}</time></div>`).join("") || `<p class="muted">Nothing yet.</p>`}</div></section>`
    );
  }
  async function loadProfile() {
    alpha.loading = true;
    try {
      alpha.profile = await PortalAPI.json("/api/auth/profile");
    } catch (err) {
      alpha.profile = { error: err.message || "Could not load your profile" };
    }
    alpha.at = Date.now();
    alpha.loading = false;
    if (state.page === "profile") render("profile");
  }

  /* ---------------- Demo Ventures support: the request form is on the page */
  const SUPPORT_TOPICS = ["Introduction request", "Legal or compliance support", "Finance or MIS support", "Hiring or HR support", "Fundraising support", "Customer or business development", "Technology or operational support", "Resource request", "Other"];
  function supportForm() {
    const founder = isFounder(PortalAPI.user);
    return `<aside class="card" id="supportFormCard"><div class="section-title"><h2>Send a request</h2></div>
      <form id="supportForm" class="form">
        <label>Topic<select name="type">${SUPPORT_TOPICS.map((t) => `<option>${t}</option>`).join("")}</select></label>
        <label>Subject<input name="subject" maxlength="200" required placeholder="A short subject"${founder ? "" : " disabled"}></label>
        <label>How can we help?<textarea name="context" maxlength="4000" required placeholder="What outcome are you looking for?"${founder ? "" : " disabled"}></textarea></label>
        <button class="btn primary wide" type="submit"${founder ? "" : " disabled"}>Send to Demo Ventures</button>
        <small class="muted">${founder ? "It goes to your Demo Ventures team and appears in your messages straight away." : "This is a preview: founders send requests here."}</small>
      </form></aside>`;
  }
  document.addEventListener("submit", async (e) => {
    if (e.target.id !== "supportForm") return;
    e.preventDefault();
    const fd = new FormData(e.target);
    const btn = e.target.querySelector('[type="submit"]');
    btn.disabled = true;
    try {
      const res = await PortalAPI.submitHelp({ subject: fd.get("subject"), context: fd.get("context"), category: fd.get("type"), resource_id: null, connect_entry_id: null });
      await Promise.all([refreshHelpFromApi(), refreshActivity()]);
      toast(`Sent · reference ${res.public_ref}`);
      render("requests");
    } catch (err) {
      toast(err.message || "Could not send your request");
      btn.disabled = false;
    }
  });

  /* ---------------- Sector updates with date and topic filters */
  /* Sector updates (partner review, 4 Nov 2026): by topic, with Latest (newest first) or All (grouped by
     topic), and a search box. The 7/30-day buttons are gone. */
  function updateCard(u) {
    return `<article class="card update-card"><div class="update-meta"><span class="tag">${esc(u.type.toUpperCase())}</span><time>${esc(u.date)}</time></div><h2>${esc(u.title)}</h2><p>${esc(u.summary)}</p>${u.why ? `<p class="update-why"><strong>Why it matters:</strong> ${esc(u.why)}</p>` : ""}<div class="update-foot"><span>Source: ${esc(u.source || "Demo Ventures")}</span>${/^https?:\/\//.test(u.url || "") ? `<a class="text-btn" href="${esc(u.url)}" target="_blank" rel="noopener noreferrer">Read the article ↗</a>` : ""}<button class="text-btn" data-action="sector-detail" data-id="${u.id}">Read brief →</button></div></article>`;
  }
  function updateMatches() {
    const words = alpha.updQuery.toLowerCase().split(/\s+/).filter(Boolean);
    return sectorUpdates
      .filter((u) => (alpha.updTopic === "All" || u.type === alpha.updTopic)
        && words.every((w) => [u.title, u.summary, u.why, u.source, u.type].join(" ").toLowerCase().includes(w)))
      .sort((a, b) => new Date(b.publishedAt || 0) - new Date(a.publishedAt || 0));
  }
  function updateResults() {
    const list = updateMatches();
    if (!list.length) return `<div class="card empty"><h3>No updates match</h3><p>${alpha.updQuery ? "Try another word or topic." : "New updates for your sector show up here."}</p></div>`;
    if (alpha.updSort === "latest") return list.map(updateCard).join("");
    const byTopic = {};
    list.forEach((u) => (byTopic[u.type] = byTopic[u.type] || []).push(u));
    return Object.entries(byTopic).map(([t, items]) => `<section class="update-group"><h3 class="update-group-title">${esc(t)} <small class="muted">${items.length}</small></h3>${items.map(updateCard).join("")}</section>`).join("");
  }
  function alphaUpdatesPage() {
    const topics = ["All", ...new Set(sectorUpdates.map((u) => u.type))];
    if (!topics.includes(alpha.updTopic)) alpha.updTopic = "All";
    const chip = (attr, v, label, on) => `<button class="chip ${on ? "active" : ""}" ${attr}="${esc(v)}">${esc(label)}</button>`;
    return (
      head("SECTOR UPDATES", "Sector Updates", `News for ${esc(companyName())}'s sector, picked by Demo Ventures from reliable sources. Each one says what it means for you and links to the original.`) +
      `<div class="page-tools"><label class="connect-search-box"><span aria-hidden="true">${svg("search")}</span><input id="updSearch" type="search" maxlength="80" placeholder="Search updates" aria-label="Search sector updates" value="${esc(alpha.updQuery)}" autocomplete="off"></label>
         <label class="sort-pick">Show<select id="updSort"><option value="latest"${alpha.updSort === "latest" ? " selected" : ""}>Latest first</option><option value="all"${alpha.updSort === "all" ? " selected" : ""}>All, by topic</option></select></label></div>
       <div class="filters" aria-label="Filter by topic">${topics.map((t) => chip("data-upd-topic", t, t === "All" ? "All topics" : t, alpha.updTopic === t)).join("")}</div>
       <section class="updates-feed" id="updResults">${updateResults()}</section>`
    );
  }
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-upd-topic]");
    if (!t) return;
    alpha.updTopic = t.dataset.updTopic;
    render("updates");
  });
  document.addEventListener("input", (e) => {
    if (e.target.id !== "updSearch") return;
    alpha.updQuery = e.target.value.trim();
    const box = document.getElementById("updResults");
    if (box) box.innerHTML = updateResults();
  });
  document.addEventListener("change", (e) => {
    if (e.target.id !== "updSort") return;
    alpha.updSort = e.target.value;
    const box = document.getElementById("updResults");
    if (box) box.innerHTML = updateResults();
  });

  /* ---------------- Events: Join button or meeting ID */
  const baseEventCard = eventCard;
  eventCard = function (e) {
    const html = baseEventCard(e);
    if (e.past || !(e.join_link || e.meeting_id)) return html;
    const join = e.join_link
      ? `<a class="btn ghost" href="${esc(e.join_link)}" target="_blank" rel="noopener noreferrer">Join meeting ↗</a>`
      : `<span class="audience" title="Meeting ID">Meeting ID: ${esc(e.meeting_id)}</span>`;
    const at = html.lastIndexOf(`<button class="text-btn" data-api-ics=`);
    return at < 0 ? html : html.slice(0, at) + join + html.slice(at);
  };


  /* ---------------- One conversation per request: follow-ups continue the same request (O5) */
  requestDetail = async function (r) {
    let d = { messages: [] };
    try {
      d = await PortalAPI.json(`/api/founder/help/${encodeURIComponent(r.id)}/messages`);
    } catch (_) {
      /* show the request even if the conversation cannot be loaded */
    }
    const founder = isFounder(PortalAPI.user);
    const msgs = d.messages.map((m) => `<div class="msg ${m.from_fund ? "ours" : "theirs"}"><small>${esc(m.author)}${m.from_fund ? " · Demo Ventures" : ""} · ${esc(relTime(m.at))}</small><p>${esc(m.body)}</p></div>`).join("");
    modal(
      r.title,
      `<span class="status ${r.resolved ? "resolved" : "progress"}">${esc(r.status)}</span>
       <div class="detail-grid" style="margin-top:12px"><div><small>Reference</small><strong>${esc(r.id)}</strong></div><div><small>Demo Ventures contact</small><strong>${esc(r.owner)}</strong></div><div><small>Sent</small><strong>${esc(r.date)}</strong></div></div>
       ${r.source ? `<p class="muted"><strong>Related to:</strong> ${esc(r.source)}${r.category ? ` · ${esc(r.category)}` : ""}</p>` : ""}
       <h3>Conversation</h3><div class="thread-list">${msgs || `<p class="muted">No messages yet.</p>`}</div>
       ${founder ? `<label>Add a follow-up<textarea name="reply" required minlength="2" maxlength="4000" placeholder="Your message is added to this same request"></textarea></label>` : `<p class="muted">Preview: founders add follow-ups here.</p>`}`,
      founder ? "Send follow-up" : "Close",
      async (fd) => {
        if (!founder) return;
        const body = String(fd.get("reply") || "").trim();
        if (!body) return;
        try {
          const res = await PortalAPI.json(`/api/founder/help/${encodeURIComponent(r.id)}/messages`, { method: "POST", body: JSON.stringify({ body }) });
          await refreshHelpFromApi();
          toast(res.reopened ? "Sent. Your request is open again with your Demo Ventures team." : "Sent to your Demo Ventures team");
          render("requests");
        } catch (err) {
          toast(err.message || "Could not send your follow-up");
        }
      }
    );
  };

  /* ---------------- Search across the whole portal (O11) */
  const search = { q: "" };
  function searchPage() {
    const q = search.q.toLowerCase();
    const hit = (...parts) => parts.join(" ").toLowerCase().includes(q);
    const res = resources.filter((r) => hit(r.title, r.desc || "", r.cat || "", r.sub || ""));
    const ups = sectorUpdates.filter((u) => hit(u.title, u.summary || "", u.type || "", u.source || ""));
    const evs = (engagement.events || []).filter((e) => !e.past && hit(e.title, e.description || "", e.location || ""));
    const people = (engagement.connect || []).filter((c) => hit(c.display_name, c.role_title || "", c.organization || "", c.subcategory || "", (c.skills || []).join(" ")));
    const group = (title, items, row) => (items.length ? `<section class="section"><div class="section-title"><h2>${title}</h2><span class="muted">${items.length}</span></div><div class="search-results">${items.slice(0, 8).map(row).join("")}</div></section>` : "");
    const total = res.length + ups.length + evs.length + people.length;
    return (
      head("SEARCH", `Results for “${esc(search.q)}”`, total ? `${total} match${total === 1 ? "" : "es"} across the portal.` : "Nothing matches. Try a shorter word, a category such as Finance, or a person's role.") +
      group("Resources", res, (r) => `<button class="card search-hit" data-action="resource-detail" data-id="${esc(r.id)}"><span class="tag">${esc(String(r.cat).toUpperCase())}</span><strong>${esc(r.title)}</strong><small>${esc(r.desc || "")}</small></button>`) +
      group("Sector updates", ups, (u) => `<button class="card search-hit" data-action="sector-detail" data-id="${esc(u.id)}"><span class="tag">${esc(String(u.type).toUpperCase())}</span><strong>${esc(u.title)}</strong><small>${esc(u.date)} · ${esc(u.source)}</small></button>`) +
      group("Events", evs, (e) => `<button class="card search-hit" data-goto="events"><span class="tag">EVENT</span><strong>${esc(e.title)}</strong><small>${esc(e.location || "")}</small></button>`) +
      group("Connect", people, (c) => `<button class="card search-hit" data-goto="connect" data-connect-find="${esc(c.display_name)}"><span class="tag">${esc(String(c.subcategory || "Connect").toUpperCase())}</span><strong>${esc(c.display_name)}</strong><small>${esc([c.role_title, c.organization].filter(Boolean).join(" · "))}</small></button>`)
    );
  }
  // Runs before the wireframe's own search handler and replaces it.
  document.addEventListener("keydown", (e) => {
    if (e.target.id !== "globalSearch" || e.key !== "Enter" || !PortalAPI.user) return;
    e.stopPropagation();
    e.preventDefault();
    search.q = e.target.value.trim();
    if (search.q) render("search");
  }, true);
  const key = document.getElementById("searchKey");
  if (key && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) key.textContent = "⌘K";
  // Ctrl+K (Windows) or Cmd+K (Mac) jumps to the search box from anywhere in the portal.
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "k" || !PortalAPI.user) return;
    const box = document.getElementById("globalSearch");
    if (!box) return;
    e.preventDefault();
    box.focus();
    box.select();
  });

  /* ---------------- Install into the page table (branding wraps these afterwards) */
  const baseInstall = installEngagementPages;
  installEngagementPages = function () {
    baseInstall();
    pages.updates = alphaUpdatesPage;
    pages.profile = profilePage;
    pages.search = searchPage;
    pages.requests = function () {
      const open = state.requests.filter((r) => !r.resolved).length;
      const list = state.requests.map((r, i) => `<button class="card request-card wide" data-action="request-detail" data-id="${i}"><i class="dot"></i><div><h3>${esc(r.title)}</h3><p>${esc(r.id)}${r.desc ? ` · ${esc(r.desc)}` : ""}</p><small class="muted">${esc(r.owner || "Demo Ventures team")}${r.source ? ` · Re: ${esc(r.source)}` : ""}</small></div><span class="status ${r.resolved ? "resolved" : "progress"}">${esc(r.status)}</span></button>`).join("");
      return head("DEMO VENTURES SUPPORT", "Demo Ventures support", "Ask Demo Ventures for help and follow each request here, with its owner and status.") +
        `<div class="split"><section><div class="section-title"><h2>Your requests</h2><span class="muted">${open} open · ${state.requests.length} in total</span></div>${list || `<p class="muted">No requests yet. Send your first one with the form.</p>`}</section>${supportForm()}</div>`;
    };
  };

  document.addEventListener("click", (e) => {
    if (e.target.closest('[data-action="account"]')) openAccount();
    const card = e.target.closest("#content .dash-stats .metric");
    if (card && state.page === "dashboard") {
      const i = [...card.parentElement.children].indexOf(card);
      render(["connect", "requests", "playbooks"][i] || "dashboard");
    }
  });

  /* ---------------- Interactive founder walkthrough: each step spotlights what to use */
  founderJourneySteps = function () {
    const user = PortalAPI.user;
    const first = (user?.full_name || "").split(" ")[0];
    const co = companyName();
    const go = (page) => () => render(page);
    // Five steps (partner review, 4 Nov 2026). "Show me" in the walkthrough card returns to a step's screen.
    return [
      { title: `Welcome${first ? ", " + first : ""}`, text: `This is ${co}'s dashboard. Sector news sits at the top, then your playbook, your next event and your open requests.`, target: "#content .dash-stats", demo: "The three cards open Connect, your requests and your playbook.", go: go("dashboard"),
        snippet: [{ stats: [["120", "Connect"], ["1", "Open requests"], ["38%", "Playbook"]] }] },
      { title: "Resources and sector news", text: "The Resource Library holds templates and guides by topic. Sector Updates brings news picked for your sector, each with what it means for you.", target: "#content .filters", demo: "Pick a topic, then download a file or ask Demo Ventures about it.", go: go("resources"),
        snippet: [{ chips: ["All", "Finance and Compliance", "Fundraising and Investor Relations", "Growth & Sales"], active: 1 }, { rows: [["Cap Table Template", "Finance and Compliance · XLSX", "Download"]] }] },
      { title: "Connect", text: "Investors, service partners, fellow portfolio founders and Demo Ventures advisors. Ask for an introduction and Demo Ventures makes it. Contact details stay private.", target: "#content .connect-search, #content .grid", demo: "Search by name, sector or city, then choose Request introduction.", go: go("connect"),
        snippet: [{ rows: [["Example Legal Associates", "Legal counsel · service partner", "Request introduction"]] }] },
      { title: "Demo Ventures support", text: "Ask for help on anything: hiring, finance, legal or fundraising. Each request shows who at Demo Ventures has it and where it stands.", target: "#supportFormCard", demo: "Pick a topic, add a subject and send it.", go: go("requests"),
        snippet: [{ fields: [["Topic", "Finance or MIS support"], ["Subject", "Need a CA for GST filings"]] }, { buttons: ["Send to Demo Ventures"] }] },
      { title: "Playbook and events", text: "Work through your 100-day playbook phase by phase, with the documents for each step. Events lists your invitations. You can replay this tour from the User journey button.", target: "#content .accordion, #content .playbook-hero", demo: "Open a phase and tick a task when your team finishes it.", go: go("playbooks"),
        snippet: [{ rows: [["Foundation · Days 1–30", "4 of 4 tasks done", "Complete"], ["Operations · Days 31–60", "1 of 4 tasks done", "Active"]] }] },
    ];
  };
})();
