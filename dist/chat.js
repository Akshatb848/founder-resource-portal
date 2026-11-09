/** Messages (partner review, 4 Nov 2026): a two-pane chat used by founders and the Demo Ventures team.
 *  Chat.mount(host, { intro }) draws the people this user can message on the left and the open conversation
 *  on the right, with a box to write, a file to attach and Send. It checks for new messages every 10 seconds
 *  while the conversation is on screen. Backend: backend/chat_api.py. No inline handlers (the CSP blocks them). */
(function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const say = (m) => (typeof window.toast === "function" ? window.toast(m) : alert(m));
  const when = (iso) => {
    if (!iso) return "";
    const d = new Date(iso), now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    return sameDay
      ? d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })
      : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) + ", " + d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  };
  const initials = (n) => String(n || "").replace(/\(.*?\)/g, "").split(/\s+/).filter(Boolean).map((x) => x[0]).join("").slice(0, 2).toUpperCase();
  const size = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

  function mount(host, cfg = {}) {
    const st = { contacts: [], current: null, thread: null, q: "", timer: null, sending: false };
    host.innerHTML = `<div class="chat">
      <aside class="chat-side" aria-label="Conversations">
        <div class="chat-side-head"><strong>People</strong><small class="muted">${esc(cfg.intro || "")}</small></div>
        <label class="chat-search"><input type="search" placeholder="Search people" aria-label="Search people" data-chat-search></label>
        <div class="chat-contacts" data-chat-contacts><p class="muted chat-empty">Loading…</p></div>
      </aside>
      <section class="chat-main" data-chat-main aria-live="polite"><div class="chat-placeholder"><p>Pick someone on the left to start a conversation.</p></div></section>
    </div>`;
    const list = host.querySelector("[data-chat-contacts]");
    const main = host.querySelector("[data-chat-main]");

    function drawContacts() {
      const words = st.q.toLowerCase().split(/\s+/).filter(Boolean);
      const shown = st.contacts.filter((c) => words.every((w) => [c.name, c.company, c.role, c.title].join(" ").toLowerCase().includes(w)));
      list.innerHTML = shown.map((c) => `<button type="button" class="chat-contact${st.current === c.id ? " active" : ""}" data-chat-open="${c.id}">
          <span class="avatar">${esc(initials(c.name))}</span>
          <span class="chat-contact-body"><span class="chat-contact-top"><strong>${esc(c.name)}</strong>${c.last_at ? `<time>${esc(when(c.last_at))}</time>` : ""}</span>
            <small class="muted">${esc([c.role, c.company].filter(Boolean).join(" · "))}</small>
            ${c.last_message ? `<small class="chat-preview">${esc(c.last_message)}</small>` : ""}</span>
          ${c.unread ? `<b class="chat-unread" aria-label="${c.unread} unread">${c.unread}</b>` : ""}</button>`).join("")
        || `<p class="muted chat-empty">${st.contacts.length ? "Nobody matches that search." : "Nobody to message yet."}</p>`;
    }

    function drawThread() {
      const t = st.thread;
      if (!t) return;
      const msgs = t.messages.map((m) => `<div class="chat-msg ${m.mine ? "mine" : "theirs"}">
          <div class="chat-bubble">${m.body ? `<p>${esc(m.body)}</p>` : ""}${m.file_name ? `<button type="button" class="chat-file" data-chat-file="${m.id}" data-name="${esc(m.file_name)}">📎 ${esc(m.file_name)}${m.file_size ? ` <small>${size(m.file_size)}</small>` : ""}</button>` : ""}</div>
          <small class="muted">${m.mine ? "You" : esc(m.author)} · ${esc(when(m.at))}${m.mine && m.read ? " · Read" : ""}</small></div>`).join("");
      main.innerHTML = `<header class="chat-head"><button type="button" class="btn ghost chat-back" data-chat-back aria-label="Back to people">←</button><span class="avatar">${esc(initials(t.with.name))}</span><div><strong>${esc(t.with.name)}</strong>${t.with.title ? `<small class="muted">${esc(t.with.title)}</small>` : ""}</div></header>
        <div class="chat-log" data-chat-log>${msgs || `<p class="muted chat-empty">No messages yet. Say hello.</p>`}</div>
        <form class="chat-compose" data-chat-form>
          <textarea name="body" rows="2" maxlength="4000" placeholder="Write a message" aria-label="Message"></textarea>
          <div class="chat-compose-row"><label class="btn ghost chat-attach">📎 Attach<input type="file" name="file" accept=".pdf,.docx,.xlsx,.pptx,.csv,.png,.jpg,.jpeg,.txt" hidden></label><small class="muted" data-chat-filename></small><button class="btn primary" type="submit">Send</button></div>
        </form>`;
      const log = main.querySelector("[data-chat-log]");
      log.scrollTop = log.scrollHeight;
      host.querySelector(".chat").classList.add("open-thread");
    }

    async function loadContacts() {
      try {
        st.contacts = await PortalAPI.json("/api/chat/contacts");
      } catch (err) {
        list.innerHTML = `<p class="muted chat-empty">${esc(err.message)}</p>`;
        return;
      }
      drawContacts();
    }

    async function openThread(id, quiet) {
      try {
        const t = await PortalAPI.json(`/api/chat/thread/${id}`);
        const changed = !st.thread || st.current !== id || t.messages.length !== st.thread.messages.length;
        st.current = id;
        st.thread = t;
        const c = st.contacts.find((x) => x.id === id);
        if (c) c.unread = 0;
        drawContacts();
        if (!quiet || changed) {
          const draft = main.querySelector('[name="body"]')?.value || "";
          drawThread();
          if (draft) main.querySelector('[name="body"]').value = draft;
        }
        cfg.onRead?.();
      } catch (err) {
        if (!quiet) say(err.message);
      }
    }

    host.addEventListener("click", async (e) => {
      const open = e.target.closest("[data-chat-open]");
      if (open) { await openThread(Number(open.dataset.chatOpen)); main.querySelector("textarea")?.focus(); return; }
      if (e.target.closest("[data-chat-back]")) { host.querySelector(".chat").classList.remove("open-thread"); return; }
      const file = e.target.closest("[data-chat-file]");
      if (file) {
        try { say(`Downloaded ${await PortalAPI.download(`/api/chat/file/${file.dataset.chatFile}`)}`); } catch (err) { say(err.message); }
      }
    });
    host.addEventListener("input", (e) => {
      if (e.target.matches("[data-chat-search]")) { st.q = e.target.value; drawContacts(); }
    });
    host.addEventListener("change", (e) => {
      if (e.target.name === "file") host.querySelector("[data-chat-filename]").textContent = e.target.files[0]?.name || "";
    });
    host.addEventListener("keydown", (e) => {
      // Enter sends; Shift+Enter starts a new line.
      if (e.target.matches('.chat-compose textarea') && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.target.form.requestSubmit(); }
    });
    host.addEventListener("submit", async (e) => {
      const form = e.target.closest("[data-chat-form]");
      if (!form) return;
      e.preventDefault();
      if (st.sending || !st.current) return;
      const fd = new FormData(form);
      if (!String(fd.get("body") || "").trim() && !(fd.get("file") && fd.get("file").size)) return;
      if (!(fd.get("file") && fd.get("file").size)) fd.delete("file");
      st.sending = true;
      form.querySelector('[type="submit"]').disabled = true;
      try {
        const resp = await PortalAPI.request(`/api/chat/thread/${st.current}`, { method: "POST", body: fd });
        if (!resp.ok) { const j = await resp.json().catch(() => ({})); throw new Error(j.detail || "Could not send the message"); }
        form.reset();
        await openThread(st.current);
        loadContacts();
        main.querySelector("textarea")?.focus();
      } catch (err) {
        say(err.message);
      } finally {
        st.sending = false;
        const btn = main.querySelector('[data-chat-form] [type="submit"]');
        if (btn) btn.disabled = false;
      }
    });

    loadContacts();
    // New messages arrive while this screen is open (stops once the host leaves the page).
    st.timer = setInterval(() => {
      if (!document.body.contains(host)) { clearInterval(st.timer); return; }
      if (document.hidden) return;
      if (st.current) openThread(st.current, true);
      else loadContacts();
    }, 10000);
    return { reload: loadContacts };
  }

  window.Chat = { mount };
})();
