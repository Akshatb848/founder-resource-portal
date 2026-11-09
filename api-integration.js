/** Portal API bridge, active only when the page is served by the portal API (same origin).
 *
 * Sessions: the server issues a token at sign-in (stored server-side, 7 days). The browser keeps it in
 * localStorage so a refresh or a second tab stays signed in. Signing out ends the server session,
 * clears local data and signs out every open tab (via the "storage" event).
 */
const TOKEN_KEY = "frp_token";
const USER_KEY = "frp_user";

function readStored(key) {
  try {
    // One-time move from the older per-tab storage.
    const legacy = sessionStorage.getItem(key);
    if (legacy && !localStorage.getItem(key)) localStorage.setItem(key, legacy);
    sessionStorage.removeItem(key);
    return localStorage.getItem(key) || "";
  } catch (_) {
    return "";
  }
}

/** The dev server marks only the browser tab title with "[DEV]"; the portal itself carries no environment label
 *  (partner review, 5 Nov 2026). Production, the laptop sandbox and test copies are unchanged. */
function markEnvironment(env) {
  if (env !== "dev") return;
  const apply = () => {
    if (!document.title.startsWith("[DEV]")) document.title = `[DEV] ${document.title}`;
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply); else apply();
}

window.PortalAPI = {
  base: "",
  token: readStored(TOKEN_KEY),
  offline: false, // true when the server could not be reached (not the same as "signed out")
  enabled: false,
  user: null,
  health: null,

  /** Find the API once per page. A failed check is retried on the next call; a successful one is reused. */
  detect() {
    if (!this._detecting) {
      this._detecting = this._detect().then((res) => {
        if (!this.enabled) this._detecting = null;
        return res;
      });
    }
    return this._detecting;
  },

  async _detect() {
    this.enabled = false;
    this.base = "";
    const host = window.location.hostname;
    // Same origin first: the API serves the frontend, so this is the normal path locally and on the VM.
    const candidates = [new URL("api/health", window.location.origin + "/").href];
    // Fallback only when the pages are opened from a separate static server on this machine.
    if ((host === "localhost" || host === "127.0.0.1") && window.location.port !== "8000") {
      candidates.push("http://127.0.0.1:8000/api/health");
    }
    if (window.location.protocol === "file:" || host.endsWith("github.io")) return null;

    for (const url of candidates) {
      try {
        const r = await fetch(url);
        const ct = r.headers.get("content-type") || "";
        if (!r.ok || !ct.includes("json")) continue;
        const data = await r.json();
        if (data.service === "founder-resource-portal") {
          this.health = data;
          markEnvironment(data.environment);
          if (data.status !== "ok") return null;
          this.base = url.replace(/\/api\/health\/?$/, "");
          this.enabled = true;
          return data.database || "ok";
        }
      } catch (_) {
        /* try next */
      }
    }
    return null;
  },

  headers(json = true) {
    const h = json ? { "Content-Type": "application/json" } : {};
    if (this.token) h.Authorization = `Bearer ${this.token}`;
    const preview = this.previewCompany();
    if (preview) h["X-Preview-Company"] = String(preview.id); // staff previewing a company's founder portal
    return h;
  },

  /** Staff only: which company's founder portal they are previewing ({id, name}) or null.
   *  A preview tab opened from the workspace carries it in the address: /?preview=<id>&company=<name>. */
  previewCompany() {
    try {
      const q = new URLSearchParams(window.location.search);
      if (q.get("preview")) {
        const fromUrl = { id: Number(q.get("preview")), name: q.get("company") || "" };
        sessionStorage.setItem("frp_preview_company", JSON.stringify(fromUrl));
        history.replaceState(null, "", window.location.pathname + window.location.hash);
        return fromUrl;
      }
    } catch (_) {}
    try {
      return JSON.parse(sessionStorage.getItem("frp_preview_company") || "null");
    } catch (_) {
      return null;
    }
  },
  setPreviewCompany(company) {
    try {
      if (company) sessionStorage.setItem("frp_preview_company", JSON.stringify({ id: company.id, name: company.name }));
      else sessionStorage.removeItem("frp_preview_company");
    } catch (_) {}
  },

  async request(path, opts = {}) {
    const send = () => fetch(`${this.base}${path}`, { ...opts, headers: { ...this.headers(!(opts.body instanceof FormData)), ...(opts.headers || {}) } });
    let r = await send();
    // 503 = the portal is very busy (no free database connection). Reads are safe to repeat: wait, retry once.
    const isRead = !opts.method || opts.method.toUpperCase() === "GET";
    if (r.status === 503 && isRead) {
      const wait = Math.min(5, Number(r.headers.get("Retry-After")) || 2) * 1000;
      await new Promise((ok) => setTimeout(ok, wait));
      r = await send();
    }
    if (r.status === 401 && this.token) {
      this.clearSession();
      window.dispatchEvent(new CustomEvent("portal:session-expired"));
    }
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      const detail = Array.isArray(err.detail) ? err.detail.map((d) => d.msg).join("; ") : err.detail;
      throw new Error(detail || `Request failed (${r.status})`);
    }
    return r;
  },

  async json(path, opts) {
    return (await this.request(path, opts)).json();
  },

  clearSession() {
    this.token = "";
    this.user = null;
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      ["frp_token", "frp_user", "frp_team_tab", "frp_journey_pending", "frp_preview_company"].forEach((k) => sessionStorage.removeItem(k));
    } catch (_) {
      /* storage blocked: the in-memory session is cleared anyway */
    }
  },

  async login(email, password) {
    const data = await this.json("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    this.token = data.token;
    this.user = data.user;
    try {
      localStorage.setItem(TOKEN_KEY, this.token);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    } catch (_) {
      /* private mode: the session lasts for this page only */
    }
    return data;
  },

  /** The signed-in user, or null. A 401 clears the session; a network or server error does not
   *  (a brief outage or restart must not sign people out) and sets this.offline instead. */
  async me() {
    this.offline = false;
    if (!this.token) return null;
    try {
      const r = await fetch(`${this.base}/api/auth/me`, { headers: this.headers() });
      if (r.status === 401 || r.status === 403) {
        this.clearSession();
        return null;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      this.user = data.user;
      try {
        localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      } catch (_) {}
      return data.user;
    } catch (_) {
      this.offline = true;
      return null;
    }
  },

  async logout() {
    try {
      if (this.enabled && this.token) await fetch(`${this.base}/api/auth/logout`, { method: "POST", headers: this.headers() });
    } catch (_) {
      /* ignore */
    }
    this.clearSession();
  },

  /** Sign out everywhere in this browser and return to the one sign-in page. */
  async signOut() {
    await this.logout();
    window.location.replace("/");
  },

  async download(path) {
    const r = await this.request(path);
    const cd = r.headers.get("content-disposition") || "";
    const m = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(cd);
    const name = m ? decodeURIComponent(m[1] || m[2]) : "resource";
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return name;
  },

  getDashboard: () => PortalAPI.json("/api/founder/dashboard").catch(() => null),
  getResources: () => PortalAPI.json("/api/founder/resources").catch(() => null),
  getConnect: () => PortalAPI.json("/api/founder/connect").catch(() => null),
  getPlaybook: () => PortalAPI.json("/api/founder/playbook").catch(() => null),
  getSectorUpdates: () => PortalAPI.json("/api/founder/sector-updates").catch(() => []),
  getActivity: () => PortalAPI.json("/api/founder/activity").catch(() => []),
  getIntake: () => PortalAPI.json("/api/founder/intake").catch(() => null),
  listHelp: () => PortalAPI.json("/api/founder/help").catch(() => []),
  submitHelp: (payload) => PortalAPI.json("/api/founder/help", { method: "POST", body: JSON.stringify(payload) }),
  submitIntake: (payload) => PortalAPI.json("/api/founder/intake", { method: "POST", body: JSON.stringify(payload) }),
  downloadResource: (id) => PortalAPI.download(`/api/founder/resources/${id}/download`),
};

// Another tab signed out, or signed in as someone else: follow it so no tab shows a stale account.
window.addEventListener("storage", (e) => {
  if (e.key !== TOKEN_KEY && e.key !== null) return;
  const now = readStored(TOKEN_KEY);
  if (now !== PortalAPI.token) window.location.replace("/");
});
