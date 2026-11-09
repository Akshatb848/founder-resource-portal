// Signed in already? Hide the sign-in form until the session is restored, so a refresh never flashes it.
try { if (localStorage.getItem("frp_token") || sessionStorage.getItem("frp_token")) document.documentElement.classList.add("restoring"); } catch (_) {}
