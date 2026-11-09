/** Messages page in the founder portal (partner review, 4 Nov 2026): chat with your Demo Ventures team
 *  (relationship manager, portfolio analyst, the Super Admin), with files. The screen is chat.js, shared with
 *  the workspace. The menu badge shows unread messages. Staff previewing the portal do not see conversations. */
(function () {
  if (!PORTAL_PAGES.includes("messages")) PORTAL_PAGES.push("messages");

  async function refreshBadge() {
    const b = document.getElementById("messagesBadge");
    if (!b || PortalAPI.user?.account_type !== "founder") return;
    try { b.textContent = (await PortalAPI.json("/api/chat/unread")).unread || ""; } catch (_) { /* the badge is a convenience */ }
  }

  function messagesPage() {
    setTimeout(() => {
      const host = document.getElementById("founderChatHost");
      if (!host || host.dataset.mounted) return;
      host.dataset.mounted = "1";
      if (PortalAPI.user?.account_type !== "founder") {
        host.innerHTML = `<div class="card empty"><p>Founders chat with their Demo Ventures team here. Conversations are private, so they don't show in a preview.</p></div>`;
        return;
      }
      Chat.mount(host, { intro: "Your Demo Ventures team", onRead: refreshBadge });
    }, 0);
    return head("MESSAGES", "Messages", "Chat with your Demo Ventures team and share files. For a formal request with an owner and status, use Demo Ventures support.") +
      `<div id="founderChatHost"></div>`;
  }

  pages.messages = messagesPage;
  const baseInstall = window.installApiPages;
  if (typeof baseInstall === "function") {
    window.installApiPages = function () {
      const r = baseInstall.apply(this, arguments);
      refreshBadge();
      setInterval(() => { if (!document.hidden) refreshBadge(); }, 30000);
      return r;
    };
  }
})();
