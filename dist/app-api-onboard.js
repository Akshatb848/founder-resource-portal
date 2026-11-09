/** Sign-in page additions (meeting 23 Oct 2026):
 *  - /?invite=<token> or /?reset=<token>: set a password with the single-use link from the invite or reset
 *    email (or WhatsApp message), then go straight into the portal.
 *  - "Forgot password?": emails a reset link (the answer never reveals whether an email has an account).
 *  - "Sign in with OTP" (30 Oct 2026), next to Google: "coming soon" until OTP_SIGNIN_ENABLED is on (off by default). */
(function () {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("invite") || params.get("reset");
  const card = () => document.getElementById("loginForm");
  if (token) {
    // Opening a link signs out whoever used this browser before, so the right account gets the password.
    try { ["frp_token", "frp_user"].forEach((k) => localStorage.removeItem(k)); } catch (_) { /* storage blocked */ }
    if (window.PortalAPI) { PortalAPI.token = ""; PortalAPI.user = null; }
  }
  const e = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const logo = () => card()?.querySelector(".login-logo")?.outerHTML || "";

  async function api(path, opts = {}) {
    const send = () => fetch(path, { ...opts, headers: { "Content-Type": "application/json" } });
    let r = await send();
    if (r.status === 503 && (!opts.method || opts.method === "GET")) { // portal very busy: wait, retry a read once
      await new Promise((ok) => setTimeout(ok, Math.min(5, Number(r.headers.get("Retry-After")) || 2) * 1000));
      r = await send();
    }
    let data = null;
    try { data = await r.json(); } catch (_) { /* empty body */ }
    if (!r.ok) throw new Error((data && (typeof data.detail === "string" ? data.detail : data.detail?.[0]?.msg)) || "Something went wrong. Try again.");
    return data;
  }

  function cleanAddress() {
    history.replaceState(null, "", window.location.pathname);
  }

  async function showSetPassword() {
    const old = card();
    if (!old) return;
    const brand = logo(); // read before the form is replaced
    const form = old.cloneNode(false); // a fresh form: the normal sign-in handler is not attached to it
    old.replaceWith(form);
    document.documentElement.classList.remove("restoring");
    form.innerHTML = `${brand}<h2>Setting up…</h2>`;
    let info;
    try {
      info = await api(`/api/auth/link/${encodeURIComponent(token)}`);
    } catch (err) {
      form.innerHTML = `${brand}<h2>This link has expired</h2><p>${e(err.message)}</p><a class="btn primary wide" href="/">Go to sign in</a>`;
      cleanAddress();
      return;
    }
    const invite = info.purpose === "invite";
    form.innerHTML = `${brand}
      <h2>${invite ? "Welcome to the Founder's Resource Portal" : "Choose a new password"}</h2>
      <p>${invite ? `Set a password for <strong>${e(info.email)}</strong>${info.company ? ` (${e(info.company)})` : ""}. You will use it with this email to sign in.` : `For <strong>${e(info.email)}</strong>.`}</p>
      <label>New password<input id="newPw" type="password" autocomplete="new-password" minlength="10" maxlength="128" required></label>
      <label>Type it again<input id="newPw2" type="password" autocomplete="new-password" minlength="10" maxlength="128" required></label>
      <small class="muted">At least 10 characters. A short sentence is easy to remember and hard to guess.</small>
      <button class="btn primary wide" type="submit">${invite ? "Set password and sign in" : "Save and sign in"} <span>→</span></button>
      <p id="setPwError" class="login-error" role="alert" hidden></p>`;
    form.onsubmit = async (ev) => {
      ev.preventDefault();
      ev.stopImmediatePropagation();
      const pw = document.getElementById("newPw").value;
      const err = document.getElementById("setPwError");
      if (pw !== document.getElementById("newPw2").value) { err.textContent = "The two passwords are different."; err.hidden = false; return; }
      const btn = form.querySelector("[type=submit]");
      btn.disabled = true;
      try {
        const res = await api("/api/auth/set-password", { method: "POST", body: JSON.stringify({ token, password: pw }) });
        try {
          localStorage.setItem("frp_token", res.token);
          localStorage.setItem("frp_user", JSON.stringify(res.user));
          if (invite) sessionStorage.setItem("frp_journey_pending", "1"); // the walkthrough opens on first sign-in
        } catch (_) { /* storage blocked: the next sign-in still works with the new password */ }
        window.location.replace(res.redirect || "/");
      } catch (x) {
        err.textContent = x.message;
        err.hidden = false;
        btn.disabled = false;
      }
    };
    document.getElementById("newPw").focus();
  }

  function addForgotLink() {
    const form = card();
    if (!form || form.querySelector("[data-forgot]")) return;
    const p = document.createElement("p");
    p.className = "login-help";
    p.innerHTML = `<button type="button" class="text-btn" data-forgot>Forgot your password?</button><span>First time here? Use the invitation link Demo Ventures emailed you.</span>`;
    form.querySelector("#loginError")?.before(p);
    p.querySelector("[data-forgot]").onclick = () => {
      const email = document.getElementById("email")?.value || "";
      const box = document.createElement("div");
      box.className = "forgot-box";
      box.innerHTML = `<label>Your email address<input id="forgotEmail" type="email" required value="${e(email)}"></label>
        <button class="btn ghost wide" type="button" data-send-reset>Email me a reset link</button><p class="muted" data-forgot-msg></p>`;
      p.replaceWith(box);
      box.querySelector("[data-send-reset]").onclick = async () => {
        const addr = box.querySelector("#forgotEmail").value.trim();
        const msg = box.querySelector("[data-forgot-msg]");
        if (!addr) { msg.textContent = "Type your email address first."; return; }
        try {
          const r = await api("/api/auth/forgot", { method: "POST", body: JSON.stringify({ email: addr }) });
          msg.textContent = r.status;
        } catch (x) {
          msg.textContent = x.message;
        }
      };
    };
  }

  // Google SSO button is a placeholder for now: it only explains that email sign-in is still the way in.
  function wireGoogleSso() {
    const btn = card()?.querySelector("[data-google-sso]");
    if (!btn) return;
    btn.onclick = () => {
      const msg = document.getElementById("loginError");
      if (!msg) return;
      msg.textContent = "Google sign-in is coming soon. Use your email and password for now.";
      msg.hidden = false;
    };
  }

  // Sign in with a one-time code by email (alpha-v1.2.6). The button sits next to Google's on the page. While the
  // feature is switched off (GET /api/auth/options says otp: false, OTP_SIGNIN_ENABLED) it only says "coming soon".
  async function addOtpOption() {
    const form = card();
    const btn = form?.querySelector("[data-otp-signin]");
    if (!btn) return;
    const soon = () => {
      const msg = document.getElementById("loginError");
      if (!msg) return;
      msg.textContent = "Sign-in by emailed code is coming soon. Use your email and password for now.";
      msg.hidden = false;
    };
    btn.onclick = soon;
    let opts = null;
    try { opts = await api("/api/auth/options"); } catch (_) { return; } // older server or offline: stays "coming soon"
    if (!opts || !opts.otp) return;
    btn.onclick = () => {
      const box = document.createElement("div");
      box.className = "forgot-box otp-box";
      box.innerHTML = `<label>Your email address<input id="otpEmail" type="email" autocomplete="username" required value="${e(document.getElementById("email")?.value || "")}"></label>
        <button class="btn ghost wide" type="button" data-otp-send>Email me a sign-in code</button>
        <div data-otp-step hidden><label>6-digit code<input id="otpCode" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}"></label>
        <button class="btn primary wide" type="button" data-otp-verify>Sign in with code <span>→</span></button></div>
        <p class="muted" data-otp-msg role="status"></p>`;
      (btn.closest(".login-alt") || btn).after(box);
      btn.disabled = true;
      const msg = box.querySelector("[data-otp-msg]");
      const email = () => box.querySelector("#otpEmail").value.trim();
      const send = box.querySelector("[data-otp-send]");
      send.onclick = async () => {
        if (!email()) { msg.textContent = "Type your email address first."; return; }
        send.disabled = true;
        try {
          const r = await api("/api/auth/otp/request", { method: "POST", body: JSON.stringify({ email: email() }) });
          msg.textContent = r.status;
          send.textContent = "Send a new code";
          box.querySelector("[data-otp-step]").hidden = false;
          box.querySelector("#otpCode").focus();
        } catch (x) {
          msg.textContent = x.message;
        }
        send.disabled = false;
      };
      const verify = box.querySelector("[data-otp-verify]");
      const go = async () => {
        const code = box.querySelector("#otpCode").value.trim();
        if (!/^\d{6}$/.test(code)) { msg.textContent = "Type the 6-digit code from the email."; return; }
        verify.disabled = true;
        try {
          const res = await api("/api/auth/otp/verify", { method: "POST", body: JSON.stringify({ email: email(), code }) });
          try {
            localStorage.setItem("frp_token", res.token);
            localStorage.setItem("frp_user", JSON.stringify(res.user));
          } catch (_) { /* storage blocked */ }
          window.location.replace(res.redirect || "/");
        } catch (x) {
          msg.textContent = x.message;
          verify.disabled = false;
        }
      };
      verify.onclick = go;
      box.querySelector("#otpCode").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); go(); } });
      box.querySelector("#otpEmail").focus();
    };
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (token) showSetPassword();
    else { addForgotLink(); wireGoogleSso(); addOtpOption(); }
  });
})();
