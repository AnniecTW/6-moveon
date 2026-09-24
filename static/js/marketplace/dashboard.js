function isPlainDashboardClick(event, link) {
  return (
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey &&
    new URL(link.href).origin === window.location.origin
  );
}

async function swapDashboard(url, { push = true } = {}) {
  const current = document.querySelector("[data-dashboard-content]");
  if (!current) {
    window.location.assign(url);
    return;
  }
  current.dataset.loading = "true";
  current.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(url, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`Dashboard request failed: ${response.status}`);
    const documentCopy = new DOMParser().parseFromString(await response.text(), "text/html");
    const replacement = documentCopy.querySelector("[data-dashboard-content]");
    if (!replacement) throw new Error("Dashboard content was missing from the response.");

    document.dispatchEvent(new CustomEvent("dashboard:before-swap"));
    current.replaceWith(replacement);
    document.title = documentCopy.title;
    if (push) history.pushState({ dashboard: true }, "", url);
    document.dispatchEvent(new CustomEvent("dashboard:content-loaded", { detail: { url } }));
    replacement.focus({ preventScroll: true });
  } catch (error) {
    window.location.assign(url);
  }
}

export function setupDashboardNavigation() {
  if (document.documentElement.dataset.dashboardNavigationReady) return;
  document.documentElement.dataset.dashboardNavigationReady = "true";

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-dashboard-tab], a[data-dashboard-route]");
    if (!link || !isPlainDashboardClick(event, link)) return;
    event.preventDefault();
    swapDashboard(link.href);
  });

  window.addEventListener("popstate", () => {
    if (document.querySelector("[data-dashboard-content]")) {
      swapDashboard(window.location.href, { push: false });
    }
  });
}
