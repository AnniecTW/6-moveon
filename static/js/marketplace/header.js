export function setupHeader() {
  const dialog = document.querySelector("[data-header-dialog]");
  const messages = {
    sell: [
      "Sell an item",
      "Listing creation is coming next. You'll be able to add photos, set your price, and choose pickup or delivery.",
    ],
  };
  document.querySelectorAll("[data-header-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const [title, message] = messages[button.dataset.headerAction];
      dialog.querySelector("h2").textContent = title;
      dialog.querySelector("p").textContent = message;
      dialog.showModal();
    });
  });
  dialog
    .querySelector("button")
    .addEventListener("click", () => dialog.close());

  const messagesLink = document.querySelector("[data-unread-url]");
  if (!messagesLink) return;
  const badge = messagesLink.querySelector("[data-message-count]");
  let refreshing = false;
  let stopped = false;
  async function refreshUnread() {
    if (document.hidden || refreshing || stopped) return;
    refreshing = true;
    try {
      const response = await fetch(messagesLink.dataset.unreadUrl, { credentials: "same-origin" });
      if (response.status === 401 || response.status === 403) {
        stopped = true;
        badge.hidden = true;
        messagesLink.setAttribute("aria-label", "Messages");
        return;
      }
      if (!response.ok) return;
      const count = Math.max(0, Number((await response.json()).unreadCount) || 0);
      badge.hidden = count === 0;
      badge.textContent = count > 99 ? "99+" : String(count);
      messagesLink.setAttribute("aria-label", count ? `Messages, ${count} unread` : "Messages");
    } catch (_) {
      // Keep the last known badge while the network is unavailable.
    } finally {
      refreshing = false;
    }
  }
  refreshUnread();
  setInterval(refreshUnread, 15000);
  document.addEventListener("visibilitychange", refreshUnread);
  window.addEventListener("messaging:unread-changed", refreshUnread);
}
