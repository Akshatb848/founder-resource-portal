/** Hiring (alpha v1.1): the company's open roles and candidate profiles featured by the Demo Ventures team.
 *  - Dashboard: a "Featured for you" card while a featured profile waits for the founder's reply.
 *  - Hiring page: openings (founders can add one, mark it filled or closed) and featured profiles.
 *  - "Interested" opens a Demo Ventures support request for the introduction; "Not a fit" closes it.
 *  Staff previewing the portal see the same screens with the founder actions switched off. */
(function () {
  const hiring = { data: null, at: 0, loading: false, error: "" };

  if (!PORTAL_PAGES.includes("hiring")) PORTAL_PAGES.push("hiring");

  async function loadHiring(force) {
    if (hiring.loading || (!force && hiring.data && Date.now() - hiring.at < 5000)) return hiring.data;
    hiring.loading = true;
    try {
      hiring.data = await PortalAPI.json("/api/founder/hiring");
      hiring.error = "";
      hiring.at = Date.now();
    } catch (err) {
      hiring.error = err.message || "Could not load hiring";
    } finally {
      hiring.loading = false;
    }
    setBadge();
    return hiring.data;
  }

  function setBadge() {
    const b = document.getElementById("hiringBadge");
    if (b) b.textContent = hiring.data?.waiting ? String(hiring.data.waiting) : "";
  }

  const canAct = () => isFounder(PortalAPI.user);

  const metaLine = (p) => [p.experience_years != null ? `${p.experience_years} yrs experience` : "", p.location || ""].filter(Boolean).join(" · ");

  /* The card is a short summary: who, for which opening, and why. "View profile" opens the full profile,
     then "Interested, arrange a conversation" and "Not a fit" follow. */
  function profileCard(p) {
    const meta = metaLine(p);
    const waiting = p.status === "featured";
    const statusClass = { featured: "review", interested: "progress", not_fit: "upcoming" }[p.status] || "upcoming";
    const view = `<button class="btn ghost" type="button" data-talent-view="${p.id}">View profile</button>`;
    const actions = waiting && canAct()
      ? `<div class="card-actions talent-actions">${view.replace("btn ghost", "btn primary")}</div>`
      : `<div class="card-actions talent-actions">${view}</div>` +
        (waiting
          ? `<p class="muted">Preview: founders reply here.</p>`
          : `<p class="muted">${p.status === "interested" ? `Request ${esc(p.request_ref || "")} is with your Demo Ventures team.` : ""}${p.founder_note ? ` Your note: ${esc(p.founder_note)}` : ""}</p>`);
    return `<article class="card talent-card${waiting ? " featured" : ""}">
      <div class="talent-head"><span class="tag">${waiting ? "FEATURED BY DEMO VENTURES" : "CANDIDATE"}</span><span class="status ${statusClass}">${esc(p.status_label)}</span></div>
      <h3>${esc(p.full_name)}</h3>
      <p class="talent-headline">${esc(p.headline)}</p>
      ${p.role_title ? `<p class="muted">For your opening: <strong>${esc(p.role_title)}</strong></p>` : ""}
      ${meta ? `<p class="muted">${esc(meta)}</p>` : ""}
      ${p.fit_note ? `<p class="talent-why"><strong>Why ${esc(p.featured_by)} suggested them:</strong> ${esc(p.fit_note)}</p>` : ""}
      ${actions}
    </article>`;
  }

  /* The full candidate profile, followed by "Interested, arrange a conversation". */
  function viewProfile(id) {
    const p = hiring.data?.profiles.find((x) => x.id == id);
    if (!p) return;
    const waiting = p.status === "featured";
    const founder = canAct();
    const featuredOn = p.featured_at ? new Date(p.featured_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "";
    const facts = [
      ["Current role", p.headline],
      ["Experience", p.experience_years != null ? `${p.experience_years} years` : ""],
      ["Location", p.location || ""],
      ["For your opening", p.role_title || "General introduction"],
      ["Suggested by", `${p.featured_by}, Demo Ventures`],
      ["Featured on", featuredOn],
    ].filter(([, v]) => v);
    modal(
      p.full_name,
      `<span class="status ${waiting ? "review" : p.status === "interested" ? "progress" : "upcoming"}">${esc(p.status_label)}</span>
       <div class="detail-grid talent-facts">${facts.map(([k, v]) => `<div><small>${esc(k)}</small><strong>${esc(v)}</strong></div>`).join("")}</div>
       <h3>Background</h3><p>${esc(p.summary)}</p>
       ${p.fit_note ? `<h3>Why ${esc(p.featured_by)} suggested them</h3><p>${esc(p.fit_note)}</p>` : ""}
       ${p.role_title ? `<h3>The opening</h3><div class="opening-box"><strong>${esc(p.role_title)}</strong><small class="muted">${esc([p.role_seniority, p.role_location].filter(Boolean).join(" · "))}</small>${p.role_notes ? `<p>${esc(p.role_notes)}</p>` : ""}</div>` : ""}
       ${otherOpenings(p)}
       ${p.profile_url ? `<p><a href="${esc(p.profile_url)}" target="_blank" rel="noopener noreferrer">Open the candidate's public profile ↗</a></p>` : ""}
       ${p.request_ref ? `<p class="muted">Introduction request ${esc(p.request_ref)} is with your Demo Ventures team.</p>` : ""}
       ${p.founder_note ? `<p class="muted">Your note: ${esc(p.founder_note)}</p>` : ""}
       ${waiting && founder ? `<div class="talent-decide"><span>Worth a conversation?</span><button class="btn ghost" type="button" data-talent-no="${p.id}">Not a fit</button></div>` : ""}
       ${waiting && !founder ? `<p class="muted">Preview: founders reply here.</p>` : ""}
       <p class="muted">Shared with your company only, with the candidate's agreement. Please keep it confidential.</p>`,
      waiting && founder ? "Arrange a conversation" : "Close",
      () => {
        // modal() hides itself after this callback, so open the next step once it has closed.
        if (waiting && founder) setTimeout(() => respond(p.id, "interested"), 0);
      }
    );
  }

  /* The company's other open roles, so a founder reviewing a candidate sees the whole hiring picture. */
  function otherOpenings(p) {
    const others = (hiring.data?.roles || []).filter((r) => r.status === "open" && r.id !== p.role_id);
    if (!others.length) return "";
    return `<h3>Also hiring for</h3><div class="other-openings">${others.map((r) => `<span class="pill">${esc(r.title)} · ${esc(r.seniority)}${r.interest_count ? ` · ${r.interest_count} interested` : ""}</span>`).join("")}</div>`;
  }

  function hiringPage() {
    if (!hiring.data && !hiring.error) {
      loadHiring().then(() => state.page === "hiring" && render("hiring"));
      return head("HIRING", "Hiring", "Loading…");
    }
    if (hiring.error && !hiring.data) return head("HIRING", "Hiring", esc(hiring.error));
    const d = hiring.data;
    const open = d.roles.filter((r) => r.status === "open");
    const others = d.roles.filter((r) => r.status !== "open");
    const featured = d.profiles.filter((p) => p.status === "featured");
    const replied = d.profiles.filter((p) => p.status !== "featured");
    const roleRow = (r) => `<div class="request-card card"><i class="dot"></i><div><h3>${esc(r.title)}</h3><p>${esc(r.seniority)}${r.location ? ` · ${esc(r.location)}` : ""} · added by ${esc(r.added_by)}${r.from_fund ? " (Demo Ventures)" : ""}${r.interest_count ? ` · ${r.interest_count} candidate${r.interest_count === 1 ? "" : "s"} interested (Demo Ventures screens them)` : ""}</p>${r.notes ? `<p>${esc(r.notes)}</p>` : ""}${r.status === "open" && canAct() ? (r.interest_link ? `<p class="interest-link"><small class="muted">Interest link to share on LinkedIn or by message:</small> <code>${esc(r.interest_link)}</code> <button class="text-btn" type="button" data-copy-interest="${esc(r.interest_link)}">Copy</button> <button class="text-btn" type="button" data-interest-link="${r.id}" data-on="0">Turn off</button></p>` : `<p><button class="text-btn" type="button" data-interest-link="${r.id}" data-on="1">Get a link candidates can use to show interest →</button></p>`) : ""}</div><div class="row-actions"><span class="status ${r.status === "open" ? "progress" : "upcoming"}">${esc(r.status_label)}</span>${canAct() ? (r.status === "open" ? `<button class="text-btn" type="button" data-role-status="filled" data-role="${r.id}">Mark filled</button><button class="text-btn" type="button" data-role-status="closed" data-role="${r.id}">Close</button>` : `<button class="text-btn" type="button" data-role-status="open" data-role="${r.id}">Reopen</button>`) : ""}</div></div>`;
    return (
      head("HIRING", "Hiring", `Tell Demo Ventures which senior roles ${esc(companyName())} is hiring for. When the team meets someone who fits, the profile is featured here and on your dashboard.`, canAct() ? `<button class="btn primary" type="button" data-action="add-opening">+ Add an opening</button>` : "") +
      `<section class="section"><div class="section-title"><h2>Featured candidates</h2><span class="muted">${featured.length} waiting for your reply</span></div>
        ${featured.length ? `<div class="grid cols-2">${featured.map((p) => profileCard(p, false)).join("")}</div>` : `<p class="muted">No featured profiles right now. Add your openings so Demo Ventures knows who to look out for.</p>`}</section>
      <section class="section"><div class="section-title"><h2>Your openings</h2><span class="muted">${open.length} open</span></div>
        ${open.length ? open.map(roleRow).join("") : `<p class="muted">No open roles yet.</p>`}
        ${others.length ? `<details class="section"><summary class="muted">Filled and closed (${others.length})</summary>${others.map(roleRow).join("")}</details>` : ""}</section>
      ${replied.length ? `<section class="section"><div class="section-title"><h2>Profiles you replied to</h2><span class="muted">${replied.length}</span></div><div class="grid cols-2">${replied.map((p) => profileCard(p, true)).join("")}</div></section>` : ""}
      <p class="muted section">Profiles are shared with your company only, with the candidate's agreement. Please keep them confidential.</p>`
    );
  }

  /* Dashboard: the featured profiles go straight under the greeting, so they are the first thing a founder sees. */
  function patchDashboardHiring() {
    const root = document.getElementById("content");
    if (!root || state.page !== "dashboard") return;
    root.querySelector("#featuredTalent")?.remove();
    const featured = (hiring.data?.profiles || []).filter((p) => p.status === "featured");
    if (!featured.length) return;
    const box = document.createElement("section");
    box.id = "featuredTalent";
    box.className = "section featured-talent";
    box.innerHTML = `<div class="section-title"><h2>${featured.length === 1 ? "A candidate for you" : `${featured.length} candidates for you`}</h2><button class="text-btn" type="button" data-goto="hiring">Open Hiring →</button></div><div class="grid ${featured.length === 1 ? "cols-1" : "cols-2"}">${featured.slice(0, 2).map((p) => profileCard(p, true)).join("")}</div>`;
    const headEl = root.querySelector(".page-head");
    if (headEl) headEl.after(box);
    else root.prepend(box);
  }

  function wrapDashboard() {
    const base = pages.dashboard;
    if (!base || base.__hiring) return;
    pages.dashboard = function () {
      const html = base.apply(this, arguments);
      setTimeout(() => {
        patchDashboardHiring();
        loadHiring().then(patchDashboardHiring);
      }, 0);
      return html;
    };
    pages.dashboard.__hiring = true;
    Object.keys(base).forEach((k) => (pages.dashboard[k] = base[k])); // keep the __api / __branded markers
  }

  function addOpening() {
    const levels = hiring.data?.seniority || ["Mid-level", "Senior", "Leadership", "CXO"];
    modal(
      "Add an opening",
      `<label>Role<input name="title" required minlength="2" maxlength="120" placeholder="e.g. VP Engineering"></label>
       <div class="row"><label>Seniority<select name="seniority">${levels.map((l) => `<option${l === "Senior" ? " selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
       <label>Location<input name="location" maxlength="120" placeholder="e.g. Bengaluru or remote"></label></div>
       <label>What the person will do (optional)<textarea name="notes" maxlength="600" placeholder="Team, scope, must-haves"></textarea></label>
       <small class="muted">Your Demo Ventures team sees this opening and features suitable profiles for you.</small>`,
      "Add opening",
      async (fd) => {
        try {
          await PortalAPI.json("/api/founder/hiring/roles", { method: "POST", body: JSON.stringify({ title: fd.get("title"), seniority: fd.get("seniority"), location: fd.get("location"), notes: fd.get("notes") }) });
          toast("Opening added. Your Demo Ventures team can see it.");
          await loadHiring(true);
          render("hiring");
        } catch (err) {
          toast(err.message || "Could not add the opening");
        }
      }
    );
  }

  function respond(id, decision) {
    const p = hiring.data?.profiles.find((x) => x.id == id);
    if (!p) return;
    const yes = decision === "interested";
    modal(
      yes ? `Meet ${p.full_name}?` : `Not a fit: ${p.full_name}`,
      yes
        ? `<p>Your Demo Ventures team will arrange a first conversation and keep you posted in Demo Ventures support.</p><label>Anything the team should know? (optional)<textarea name="note" maxlength="600" placeholder="e.g. Available times, questions for the candidate"></textarea></label>`
        : `<label>What is missing? (optional, helps Demo Ventures suggest better profiles)<textarea name="note" maxlength="600" placeholder="e.g. Need more manufacturing experience"></textarea></label>`,
      yes ? "Request introduction" : "Send reply",
      async (fd) => {
        try {
          const r = await PortalAPI.json(`/api/founder/hiring/profiles/${id}/respond`, { method: "POST", body: JSON.stringify({ decision, note: fd.get("note") }) });
          toast(yes ? `Introduction requested (${r.request_ref}). Track it in Demo Ventures support.` : "Thanks. Demo Ventures will keep looking.");
          await loadHiring(true);
          if (yes && typeof refreshHelpFromApi === "function") await refreshHelpFromApi();
          if (yes) {
            const dash = await PortalAPI.getDashboard().catch(() => null); // "Active messages" now counts the new request
            if (dash) { apiState.dashboard = dash; state.dashboardMetrics = dash.metrics; }
          }
          render(state.page);
        } catch (err) {
          toast(err.message || "Could not send your reply");
        }
      }
    );
  }

  async function setInterestLink(id, on) {
    try {
      await PortalAPI.json(`/api/founder/hiring/roles/${id}/link`, { method: "POST", body: JSON.stringify({ on }) });
      toast(on ? "Link ready. Copy it and share it; Demo Ventures screens everyone who replies." : "Link turned off");
      await loadHiring(true);
      render("hiring");
    } catch (err) {
      toast(err.message || "Could not change the link");
    }
  }

  async function setRoleStatus(id, status) {
    try {
      await PortalAPI.json(`/api/founder/hiring/roles/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
      toast({ filled: "Marked as filled", closed: "Opening closed", open: "Opening reopened" }[status]);
      await loadHiring(true);
      render("hiring");
    } catch (err) {
      toast(err.message || "Could not update the opening");
    }
  }

  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-talent-view],[data-talent-yes],[data-talent-no],[data-role-status],[data-action='add-opening'],[data-interest-link],[data-copy-interest]");
    if (!el || !PortalAPI.user) return;
    if (el.dataset.copyInterest) { navigator.clipboard?.writeText(el.dataset.copyInterest).then(() => toast("Link copied"), () => toast("Select the link and press Ctrl+C")); return; }
    if (el.dataset.interestLink) { setInterestLink(el.dataset.interestLink, el.dataset.on === "1"); return; }
    if (el.dataset.talentView) viewProfile(el.dataset.talentView);
    else if (el.dataset.talentYes) respond(el.dataset.talentYes, "interested");
    else if (el.dataset.talentNo) respond(el.dataset.talentNo, "not_fit");
    else if (el.dataset.roleStatus) setRoleStatus(el.dataset.role, el.dataset.roleStatus);
    else if (el.dataset.action === "add-opening" && canAct()) addOpening();
  });

  pages.hiring = hiringPage;
  // installApiPages (on sign-in) wraps the dashboard again; make sure ours is still the outer layer.
  const baseInstall = window.installApiPages;
  if (typeof baseInstall === "function") {
    window.installApiPages = function () {
      const r = baseInstall.apply(this, arguments);
      wrapDashboard();
      if (!pages.hiring.__branded) {
        const inner = pages.hiring;
        pages.hiring = function () { return brandHtml(inner()); };
        pages.hiring.__branded = true;
      }
      loadHiring(true);
      return r;
    };
  }
})();
