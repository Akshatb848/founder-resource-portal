/** Company profile page in the founder portal (alpha v1.2.6). The screen itself is company-profile.js,
 *  shared with the workspace. Founders view and edit their own company; staff previewing the portal see it
 *  read-only. The menu badge counts certificates that have expired or expire soon. */
(function () {
  if (!PORTAL_PAGES.includes("company")) PORTAL_PAGES.push("company");

  function setBadge(prof) {
    const b = document.getElementById("companyBadge");
    if (b) b.textContent = prof && prof.alerts && prof.alerts.length ? String(prof.alerts.length) : "";
  }

  function companyPage() {
    // Mounted after the page HTML is in place (render() writes it into #content first).
    setTimeout(() => {
      const host = document.getElementById("companyProfileHost");
      if (!host || host.dataset.mounted) return;
      host.dataset.mounted = "1";
      CompanyProfile.mount(host, {
        url: "/api/founder/profile", confirmUrl: "/api/founder/profile/confirm",
        pdfUrl: "/api/founder/profile.pdf", firmsUrl: "/api/founder/firms", onSaved: setBadge,
      });
    }, 0);
    return head("YOUR COMPANY", "Company profile",
      "Your company's details in one place: governance, service providers, compliance and credit. Your Demo Ventures team sees the same profile, so keep it up to date.") +
      `<div id="companyProfileHost"></div>`;
  }

  pages.company = companyPage;

  // Load the alert count once after sign-in, for the menu badge.
  const baseInstall = window.installApiPages;
  if (typeof baseInstall === "function") {
    window.installApiPages = function () {
      const r = baseInstall.apply(this, arguments);
      PortalAPI.json("/api/founder/profile").then(setBadge).catch(() => setBadge(null));
      return r;
    };
  }
})();
