/** Playbook lessons (meeting 1, 26 Oct 2026; merged into the Playbook page 27 Oct 2026): the 100-Day Playbook
 *  chapter by chapter, with short lessons, the matching templates, and progress per founder. They show as the
 *  "Lessons" view of the Playbook page, not as a page of their own. Staff previewing the portal can read but not
 *  mark lessons. Old links to #course open the Playbook on its Lessons view. */
(function () {
  const course = { data: null, at: 0, loading: false, error: "", lesson: null };
  if (!PORTAL_PAGES.includes("course")) PORTAL_PAGES.push("course"); // old links: redirected below
  const onLessons = () => state.page === "playbooks" && engagement.pbView === "lessons";

  // One request at a time: callers during a load share it, so a render that asks again cannot loop.
  async function loadCourse(force) {
    if (course.loading) return course.loading;
    if (!force && course.data && Date.now() - course.at < 5000) return course.data;
    course.loading = (async () => {
      try {
        course.data = await PortalAPI.json("/api/founder/course");
        course.error = "";
        course.at = Date.now();
      } catch (err) {
        course.error = err.message || "Could not load the course";
      } finally {
        course.loading = null;
      }
      return course.data;
    })();
    return course.loading;
  }
  // Load once, then redraw the Playbook if it is still on screen. Repeat calls while loading do nothing.
  function loadThenRender() {
    if (course.loading) return;
    loadCourse().then(() => state.page === "playbooks" && (course.data || course.error) && render("playbooks"));
  }

  // Lesson text: blank lines separate paragraphs; lines starting with "- " are bullet points.
  function lessonHtml(text) {
    return String(text || "").split(/\n\s*\n/).map((block) => {
      const lines = block.split("\n").map((l) => l.trim()).filter(Boolean);
      if (lines.length && lines.every((l) => l.startsWith("- "))) return `<ul>${lines.map((l) => `<li>${esc(l.slice(2))}</li>`).join("")}</ul>`;
      const head = lines.filter((l) => !l.startsWith("- "));
      const bullets = lines.filter((l) => l.startsWith("- "));
      return `${head.length ? `<p>${head.map(esc).join("<br>")}</p>` : ""}${bullets.length ? `<ul>${bullets.map((l) => `<li>${esc(l.slice(2))}</li>`).join("")}</ul>` : ""}`;
    }).join("");
  }

  function allLessons() {
    return (course.data?.chapters || []).flatMap((c) => c.lessons.map((l) => ({ ...l, chapter: c })));
  }

  function lessonPanel(id) {
    const list = allLessons();
    const i = list.findIndex((l) => l.id === id);
    if (i < 0) return "";
    const l = list[i];
    const next = list[i + 1];
    const founder = isFounder(PortalAPI.user);
    return `<section class="card lesson-panel" id="lessonPanel">
      <span class="eyebrow">CHAPTER ${l.chapter.number} · ${esc(l.chapter.title.toUpperCase())}</span>
      <h2>${esc(l.title)}</h2><p class="muted">${l.minutes} min read${l.done ? " · done" : ""}</p>
      <div class="lesson-body">${lessonHtml(l.body)}</div>
      ${l.resource_id ? (l.resource_is_guide
        ? `<p><button class="btn ghost" type="button" data-guide-download="${l.resource_id}">Download the guide: ${esc(l.resource_title)}</button></p>`
        : `<p><button class="btn ghost" type="button" data-action="resource-detail" data-id="${l.resource_id}">Open template: ${esc(l.resource_title)} →</button></p>`) : ""}
      ${l.video_url ? `<p><a class="btn ghost" href="${esc(l.video_url)}" target="_blank" rel="noopener noreferrer">Watch the video ↗</a></p>` : ""}
      <div class="card-actions talent-actions">
        ${founder ? `<button class="btn ${l.done ? "ghost" : "primary"}" type="button" data-lesson-done="${l.id}" data-on="${l.done ? 0 : 1}">${l.done ? "Mark as not done" : "Mark as done"}</button>` : `<span class="muted">Preview: founders mark lessons done here.</span>`}
        ${next ? `<button class="btn ghost" type="button" data-lesson="${next.id}">Next: ${esc(next.title)} →</button>` : ""}
        <button class="btn ghost" type="button" data-lesson-close>Back to all chapters</button>
      </div></section>`;
  }

  // The Lessons view of the Playbook page (rendered by apiPlaybooksPage below its tabs).
  function lessonsSection() {
    if (!course.data && !course.error) {
      if (!course.loading) loadCourse().then(() => onLessons() && (course.data || course.error) && render("playbooks"));
      return `<p class="muted">Loading the lessons…</p>`;
    }
    if (course.error && !course.data) return `<div class="card empty"><p>${esc(course.error)}</p></div>`;
    const d = course.data;
    if (!d.chapters.length) return `<div class="card empty"><h3>Lessons are on their way</h3><p>Demo Ventures is preparing the playbook lessons.</p></div>`;
    const phases = [...new Set(d.chapters.map((c) => c.phase))];
    const firstOpen = allLessons().find((l) => !l.done);
    return (
      `<section class="card lessons-progress"><div><span class="eyebrow">YOUR LESSONS</span><h2>${d.done} of ${d.total} lessons done</h2><p class="muted">${d.chapters.length} chapters across the four phases${d.team_done > d.done ? ` · your team has completed ${d.team_done} between you` : ""}.</p></div>` +
      `<div class="lessons-progress-side"><div class="lesson-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${d.pct}"><span style="width:${d.pct}%"></span></div><strong>${d.pct}%</strong>` +
      (firstOpen ? `<button class="btn primary" type="button" data-lesson="${firstOpen.id}">${d.done ? "Continue" : "Start"}: ${esc(firstOpen.title)}</button>` : `<span class="status resolved">All lessons done</span>`) +
      `</div></section>` +
      guidesBlock(d.guides) +
      (course.lesson ? lessonPanel(course.lesson) : "") +
      phases.map((ph) => `<section class="section"><div class="section-title"><h2>${esc(ph)}</h2></div><div class="grid cols-2">${d.chapters.filter((c) => c.phase === ph).map((c) => `
        <article class="card chapter-card"><span class="tag">CHAPTER ${c.number}</span><h3>${esc(c.title)}</h3>${c.summary ? `<p class="muted">${esc(c.summary)}</p>` : ""}
          <ol class="lesson-list">${c.lessons.map((l) => `<li><button class="text-btn lesson-link${l.done ? " done" : ""}" type="button" data-lesson="${l.id}">${l.done ? "✓ " : ""}${esc(l.title)}</button><small class="muted"> · ${l.minutes} min</small></li>`).join("")}</ol>
          <small class="muted">${c.done} of ${c.lessons.length} done</small></article>`).join("")}</div></section>`).join("")
    );
  }

  // The full manuals the lessons are drawn from (moved here from the Resource Library on 29 Oct 2026).
  function guidesBlock(guides) {
    if (!guides || !guides.length) return "";
    return `<section class="section"><div class="section-title"><h2>Playbooks and guides</h2><span class="muted">Full manuals to download</span></div><div class="grid cols-2">${guides.map((g) => `
      <article class="card resource-card"><span class="tag">PLAYBOOK GUIDE${g.type ? ` · ${esc(g.type)}` : ""}</span><h3>${esc(g.title)}</h3><p class="muted">${esc(g.description || "")}</p>
        <div class="card-actions" style="margin-top:auto;padding-top:12px"><button class="btn primary" type="button" data-guide-download="${g.id}">Download</button></div></article>`).join("")}</div></section>`;
  }

  async function markDone(id, on) {
    try {
      const r = await PortalAPI.json(`/api/founder/course/lessons/${id}/complete`, { method: "POST", body: JSON.stringify({ done: on }) });
      await loadCourse(true);
      toast(on ? `Lesson done · lessons ${r.pct}%` : "Marked as not done");
      if (on) {
        const list = allLessons();
        const i = list.findIndex((l) => l.id === Number(id));
        if (list[i + 1]) course.lesson = list[i + 1].id;
      }
      render("playbooks");
      document.getElementById("lessonPanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      toast(err.message || "Could not save");
    }
  }

  document.addEventListener("click", (e) => {
    const g = e.target.closest("[data-guide-download]");
    if (g && PortalAPI.user && onLessons()) { apiDownload(Number(g.dataset.guideDownload)); return; }
    const el = e.target.closest("[data-lesson],[data-lesson-done],[data-lesson-close]");
    if (!el || !PortalAPI.user || !onLessons()) return;
    if (el.dataset.lessonDone) { markDone(el.dataset.lessonDone, el.dataset.on === "1"); return; }
    if (el.hasAttribute("data-lesson-close")) { course.lesson = null; render("playbooks"); return; }
    course.lesson = Number(el.dataset.lesson);
    render("playbooks");
    document.getElementById("lessonPanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  window.PlaybookLessons = {
    section: lessonsSection,
    // The playbook guides (full manuals) on the checklist view too.
    guides: () => {
      if (!course.data && !course.error) { loadThenRender(); return ""; }
      return guidesBlock(course.data?.guides);
    },
    summary: () => course.data, // for the "Open lessons" button on the playbook card
    load: loadThenRender,
  };
  // Old address #course (bookmarks, notifications): open the Playbook on its Lessons view.
  pages.course = () => { engagement.pbView = "lessons"; return pages.playbooks(); };
  const baseRender = window.render;
  window.render = function (page) {
    if (page === "course") { engagement.pbView = "lessons"; page = "playbooks"; }
    return baseRender.call(this, page, ...[].slice.call(arguments, 1));
  };
})();
