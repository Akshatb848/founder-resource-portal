/** User journey: a guided, interactive walkthrough shown after every sign-in (founders and each staff tier).
 *  The walkthrough card is docked to the right of the screen (at the bottom on phones) and the page makes
 *  room for it, so the highlighted part of the page is never covered.
 *  Steps: [{ title, text, go?, target?, demo?, snippet? }]
 *    go       opens the matching screen
 *    target   CSS selector list (first visible match wins) of the control to highlight
 *    demo     the "Try it" line: what to do there
 *    snippet  a small preview of the feature, as blocks:
 *             { stats: [[value, label], ...] } | { rows: [[title, meta, pill?], ...] } | { fields: [[label, value], ...] }
 *             { chips: [label, ...], active?: index } | { buttons: [label, ...] } (first is primary) | { note: "text" }
 *  The user can skip at any step and replay it later from the "User journey" button. */
(function () {
  const PENDING_KEY = "frp_journey_pending";
  let state = null;
  let spot = null;
  let pollTimer = null;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  function ensureOverlay() {
    let o = document.getElementById("userJourney");
    if (o) return o;
    o = document.createElement("div");
    o.id = "userJourney";
    o.className = "tour user-journey hidden";
    o.setAttribute("role", "dialog");
    o.setAttribute("aria-modal", "false");
    o.setAttribute("aria-labelledby", "ujTitle");
    o.innerHTML = `<div class="tour-step">
      <div class="uj-top"><span id="ujCount"></span><button type="button" class="text-btn" id="ujSkip">Skip journey</button></div>
      <h3 id="ujTitle"></h3><p id="ujText"></p><div class="uj-demo hidden" id="ujDemoBox"><p id="ujDemo"></p><button type="button" class="text-btn" id="ujShow">Show me</button></div>
      <figure class="uj-snippet hidden" id="ujSnippet" aria-label="Preview of this feature"></figure>
      <div class="uj-dots" id="ujDots" aria-hidden="true"></div>
      <div class="uj-actions"><button type="button" class="btn ghost" id="ujBack">Back</button><button type="button" class="btn primary" id="ujNext">Next →</button></div>
    </div>`;
    document.body.appendChild(o);
    o.querySelector("#ujSkip").onclick = () => end("skipped");
    o.querySelector("#ujBack").onclick = () => show(state.i - 1);
    // Clicking around the page mid-tour is fine: "Show me" brings the step's screen and highlight back.
    o.querySelector("#ujShow").onclick = () => show(state.i);
    o.querySelector("#ujNext").onclick = () => (state.i === state.steps.length - 1 ? end("finished") : show(state.i + 1));
    document.addEventListener("keydown", (e) => {
      if (!state || o.classList.contains("hidden")) return;
      if (e.key === "Escape") end("skipped");
      else if (e.key === "ArrowRight") o.querySelector("#ujNext").click();
      else if (e.key === "ArrowLeft" && state.i > 0) show(state.i - 1);
    });
    return o;
  }

  /* ---- feature preview ("snippet") */
  function renderSnippet(title, blocks) {
    const part = (b) => {
      if (b.stats) return `<div class="ujs-stats">${b.stats.map(([v, l]) => `<div class="ujs-stat"><strong>${esc(v)}</strong><span>${esc(l)}</span></div>`).join("")}</div>`;
      if (b.rows) return `<div class="ujs-rows">${b.rows.map(([t, m, p]) => `<div class="ujs-row"><span><b>${esc(t)}</b>${m ? `<small>${esc(m)}</small>` : ""}</span>${p ? `<i>${esc(p)}</i>` : ""}</div>`).join("")}</div>`;
      if (b.fields) return `<div class="ujs-fields">${b.fields.map(([l, v]) => `<label><span>${esc(l)}</span><em>${esc(v)}</em></label>`).join("")}</div>`;
      if (b.chips) return `<div class="ujs-chips">${b.chips.map((c, i) => `<span class="${i === (b.active ?? 0) ? "on" : ""}">${esc(c)}</span>`).join("")}</div>`;
      if (b.buttons) return `<div class="ujs-buttons">${b.buttons.map((t, i) => `<span class="${i === 0 ? "primary" : ""}">${esc(t)}</span>`).join("")}</div>`;
      if (b.note) return `<p class="ujs-note">${esc(b.note)}</p>`;
      return "";
    };
    return `<figcaption><span>Preview</span>${esc(title)}</figcaption><div class="ujs-screen">${blocks.map(part).join("")}</div>`;
  }

  /* ---- highlight the step's control, once its screen has loaded */
  function clearSpot() {
    clearInterval(pollTimer);
    if (spot) spot.classList.remove("uj-spot");
    spot = null;
  }
  function findTarget(sel) {
    for (const one of sel.split(",")) {
      const n = document.querySelector(one.trim());
      if (n && n.offsetParent !== null) return n;
    }
    return null;
  }
  function spotlight(step, o) {
    clearSpot();
    o.classList.remove("uj-clear");
    if (!step.target) return;
    let tries = 0;
    pollTimer = setInterval(() => {
      const n = findTarget(step.target);
      if (!n && ++tries < 20) return;
      clearInterval(pollTimer);
      if (!n || !state) return;
      spot = n;
      n.classList.add("uj-spot");
      o.classList.add("uj-clear");
      const phone = window.matchMedia("(max-width: 900px)").matches;
      n.scrollIntoView({ block: phone ? "start" : "center", behavior: "smooth" });
    }, 100);
  }

  function show(i) {
    const o = ensureOverlay();
    state.i = Math.max(0, Math.min(state.steps.length - 1, i));
    const step = state.steps[state.i];
    try {
      step.go && step.go();
    } catch (_) {
      /* a screen that fails to load must not trap the user in the journey */
    }
    o.querySelector("#ujCount").textContent = `${state.title} · ${state.i + 1} / ${state.steps.length}`;
    o.querySelector("#ujTitle").textContent = step.title;
    o.querySelector("#ujText").textContent = step.text;
    const demo = o.querySelector("#ujDemo");
    demo.textContent = step.demo || "";
    o.querySelector("#ujDemoBox").classList.toggle("hidden", !step.demo);
    const snip = o.querySelector("#ujSnippet");
    snip.innerHTML = step.snippet ? renderSnippet(step.title, step.snippet) : "";
    snip.classList.toggle("hidden", !step.snippet);
    o.querySelector("#ujDots").innerHTML = state.steps.map((_, n) => `<i class="${n === state.i ? "on" : ""}"></i>`).join("");
    o.querySelector("#ujBack").disabled = state.i === 0;
    o.querySelector("#ujNext").textContent = state.i === state.steps.length - 1 ? "Start using the portal" : "Next →";
    o.classList.remove("hidden");
    document.documentElement.classList.add("uj-open"); // the page makes room for the docked card
    o.querySelector(".tour-step").scrollTop = 0;
    spotlight(step, o);
    o.querySelector("#ujNext").focus({ preventScroll: true });
  }

  function end(reason) {
    const o = ensureOverlay();
    o.classList.add("hidden");
    document.documentElement.classList.remove("uj-open");
    clearSpot();
    const done = state && state.onEnd;
    state = null;
    if (done) done(reason);
  }

  window.UserJourney = {
    /** Start a journey. opts: { title, onEnd(reason: "finished" | "skipped") } */
    start(steps, opts = {}) {
      if (!steps || !steps.length) return;
      state = { steps, i: 0, title: opts.title || "User journey", onEnd: opts.onEnd };
      show(0);
    },
    /** Mark that the next page after sign-in should open the journey. */
    markPending() {
      try {
        sessionStorage.setItem(PENDING_KEY, "1");
      } catch (_) {}
    },
    /** True once per sign-in: consumes the pending flag. */
    takePending() {
      try {
        const v = sessionStorage.getItem(PENDING_KEY) === "1";
        sessionStorage.removeItem(PENDING_KEY);
        return v;
      } catch (_) {
        return false;
      }
    },
    isOpen: () => !!state,
  };
})();
