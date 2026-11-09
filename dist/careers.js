/* Public interest page for one opening (careers.html?r=<token>). Candidates register interest; the Demo Ventures
   team screens it in the workspace (Hiring → Candidate interest) before anything reaches the founders. */
(function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const token = new URLSearchParams(window.location.search).get("r") || "";
  const opening = document.getElementById("opening");
  const formCard = document.getElementById("formCard");
  const form = document.getElementById("interestForm");
  const err = document.getElementById("formError");

  async function api(path, opts = {}) {
    const send = () => fetch(path, { ...opts, headers: { "Content-Type": "application/json" } });
    let r = await send();
    if (r.status === 503 && (!opts.method || opts.method === "GET")) { // portal very busy: wait, retry a read once
      await new Promise((ok) => setTimeout(ok, Math.min(5, Number(r.headers.get("Retry-After")) || 2) * 1000));
      r = await send();
    }
    let data = null;
    try { data = await r.json(); } catch (_) { /* empty */ }
    if (!r.ok) {
      const d = data && data.detail;
      throw new Error(typeof d === "string" ? d : (d && d[0] && `${d[0].loc?.slice(-1)[0] || "field"}: ${d[0].msg}`) || "Something went wrong. Please try again.");
    }
    return data;
  }

  async function load() {
    if (!token) {
      opening.innerHTML = `<h1>Opening not found</h1><p class="muted">This link is incomplete. Ask the person who shared it for the full link.</p>`;
      return;
    }
    try {
      const o = await api(`/api/public/opening/${encodeURIComponent(token)}`);
      document.title = `${o.title} · ${o.company}`;
      const meta = [o.seniority, o.location || o.city].filter(Boolean).join(" · ");
      opening.innerHTML = `<span class="eyebrow">${esc(o.company)}</span><h1>${esc(o.title)}</h1>${meta ? `<p class="muted">${esc(meta)}</p>` : ""}
        ${o.notes ? `<p>${esc(o.notes)}</p>` : ""}${o.website ? `<p><a href="${/^https?:\/\//i.test(o.website) ? esc(o.website) : "#"}" target="_blank" rel="noopener noreferrer">About ${esc(o.company)} ↗</a></p>` : ""}`;
      formCard.classList.remove("hidden");
    } catch (e) {
      opening.innerHTML = `<h1>This opening is closed</h1><p class="muted">${esc(e.message)}</p>`;
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.hidden = true;
    if (!form.checkValidity()) { form.reportValidity(); return; }
    const fd = new FormData(form);
    const years = String(fd.get("experience_years") || "").trim();
    const body = {
      full_name: fd.get("full_name"), email: fd.get("email"), phone: fd.get("phone") || null, headline: fd.get("headline"),
      experience_years: years ? Number(years) : null, location: fd.get("location") || null, profile_url: fd.get("profile_url") || null,
      note: fd.get("note") || null, consent: fd.get("consent") === "on", website: fd.get("website") || null,
    };
    const btn = form.querySelector("[type=submit]");
    btn.disabled = true;
    try {
      const r = await api(`/api/public/opening/${encodeURIComponent(token)}/interest`, { method: "POST", body: JSON.stringify(body) });
      formCard.innerHTML = `<h2>Thank you</h2><p>${esc(r.status)}</p>`;
    } catch (x) {
      err.textContent = x.message;
      err.hidden = false;
      btn.disabled = false;
    }
  });

  load();
})();
