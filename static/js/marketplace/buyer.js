let pendingCancelCard;
const WATCHLIST_KEY = "moveon:favorites";

function readWatchlist() {
  try {
    const value = JSON.parse(localStorage.getItem(WATCHLIST_KEY) || "[]");
    return new Set(Array.isArray(value) ? value.map(String) : []);
  } catch {
    return new Set();
  }
}

function paintWatchlist() {
  const page = document.querySelector("[data-watchlist-page]");
  if (!page) return;
  const saved = readWatchlist();
  const category = page.querySelector("[data-watchlist-category]")?.value || "all";
  const sort = page.querySelector("[data-watchlist-sort]")?.value || "recent";
  let visible = 0;
  const rows = [...page.querySelectorAll("[data-watchlist-row]")];
  rows.sort((a, b) => {
    if (sort === "price-low") return Number(a.dataset.watchlistPrice) - Number(b.dataset.watchlistPrice);
    if (sort === "price-high") return Number(b.dataset.watchlistPrice) - Number(a.dataset.watchlistPrice);
    return Number(b.dataset.watchlistCreated) - Number(a.dataset.watchlistCreated);
  }).forEach((row) => page.querySelector("[data-watchlist-items]")?.append(row));
  rows.forEach((row) => {
    const active = saved.has(row.dataset.listingId) && (
      category === "all" || row.dataset.watchlistCategoryValue === category
    );
    row.classList.toggle("is-saved", active);
    visible += Number(active);
  });
  const count = page.querySelector("[data-watchlist-count]");
  if (count) count.textContent = `${visible} saved item${visible === 1 ? "" : "s"}`;
  page.querySelector("[data-watchlist-empty]")?.classList.toggle("is-visible", visible === 0);
}

function updateBuyerChart() {
  const card = document.querySelector(".buyer-spending-card");
  const dataNode = document.querySelector("#buyer-chart-data");
  if (!card || !dataNode) return;
  let points = [];
  try { points = JSON.parse(dataNode.textContent); } catch { return; }
  const selectedTypes = new Set(
    [...card.querySelectorAll("[data-chart-type]:checked")].map((input) => input.value),
  );
  const start = card.querySelector('[data-chart-date="start"]')?.value || "";
  const end = card.querySelector('[data-chart-date="end"]')?.value || "";
  const filtered = points.filter((point) => (
    selectedTypes.has(point.type) && (!start || point.date >= start) && (!end || point.date <= end)
  ));
  const spent = filtered.reduce((sum, point) => sum + Number(point.spent || 0), 0);
  const saved = filtered.reduce((sum, point) => sum + Number(point.saved || 0), 0);
  const scale = Math.max(spent, saved, 1);
  const money = (value) => `$${Math.round(value).toLocaleString()}`;
  for (const key of ["spent", "saved"]) {
    const value = key === "spent" ? spent : saved;
    const height = Math.round(value / scale * 100);
    const bar = card.querySelector(`[data-chart-bar="${key}"]`);
    bar?.setAttribute("height", String(height));
    bar?.setAttribute("y", String(100 - height));
    const label = card.querySelector(`[data-chart-value="${key}"]`);
    const legend = card.querySelector(`[data-chart-legend="${key}"]`);
    if (label) label.textContent = money(value);
    if (legend) legend.textContent = money(value);
  }
  const maxLabel = card.querySelector("[data-chart-max]");
  if (maxLabel) maxLabel.textContent = money(Math.max(spent, saved));
  const summary = card.querySelector("[data-chart-summary]");
  if (summary) summary.textContent = `You’ve saved ${money(saved)} across the selected activity.`;
  const count = card.querySelector("[data-chart-type-count]");
  if (count) count.textContent = `${selectedTypes.size} selected`;
  card.querySelector(".buyer-bar-chart")?.setAttribute(
    "aria-label", `Total spent ${money(spent)} and estimated retail savings ${money(saved)}`,
  );
}

export function setupBuyerPickups() {
  if (document.documentElement.dataset.buyerPickupsReady) return;
  document.documentElement.dataset.buyerPickupsReady = "true";

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-buyer-action]");
    if (!button) return;
    const card = button.closest(".pickup-card");
    const status = card?.querySelector("[data-pickup-status]");
    if (!status) return;
    if (button.dataset.buyerAction === "message") {
      status.textContent = "Messaging UI is not connected yet. The existing conversation model will power this action.";
    } else {
      status.textContent = "Completion and peer rating are not connected yet. No transaction was changed.";
    }
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-bundle-action]");
    if (!button) return;
    const card = button.closest(".saved-bundle-card");
    const status = card?.querySelector("[data-bundle-status]");
    if (!status) return;
    if (button.dataset.bundleAction === "details") {
      status.textContent = "The full bundle detail route is not connected yet; all current items are shown above.";
    } else if (button.dataset.bundleAction === "contact") {
      status.textContent = "Buyer messaging UI is not connected yet. Existing conversations will power this action.";
    } else {
      const dialog = document.querySelector("[data-bundle-cancel-dialog]");
      if (!dialog || typeof dialog.showModal !== "function") return;
      pendingCancelCard = card;
      dialog.querySelector("[data-cancel-bundle-name]").textContent = button.dataset.bundleName;
      dialog.showModal();
    }
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest("[data-confirm-bundle-cancel]")) return;
    const status = pendingCancelCard?.querySelector("[data-bundle-status]");
    if (status) status.textContent = "Cancellation preview confirmed. No bundle data was changed.";
    pendingCancelCard = undefined;
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-history-action]");
    if (!button) return;
    const status = button.closest(".history-row")?.querySelector("[data-history-status]");
    if (!status) return;
    status.textContent = button.dataset.historyAction === "receipt"
      ? "Receipt details are not connected yet; the CSV export contains the available purchase record."
      : "Seller ratings are not stored in the current data model yet.";
  });

  document.addEventListener("input", (event) => {
    if (!event.target.matches("[data-history-search]")) return;
    const page = event.target.closest(".purchase-history-page");
    const query = event.target.value.trim().toLowerCase();
    let visible = 0;
    page?.querySelectorAll("[data-history-row]").forEach((row) => {
      const matches = row.dataset.historyText.toLowerCase().includes(query);
      row.hidden = !matches;
      visible += Number(matches);
    });
    const empty = page?.querySelector("[data-history-empty]");
    if (empty) empty.hidden = visible !== 0;
  });

  document.addEventListener("change", (event) => {
    if (!event.target.matches("[data-history-sort]")) return;
    const list = event.target.closest(".purchase-history-page")?.querySelector("[data-history-list]");
    if (!list) return;
    const direction = event.target.value === "oldest" ? 1 : -1;
    [...list.querySelectorAll("[data-history-row]")]
      .sort((a, b) => direction * (new Date(a.dataset.historyDate) - new Date(b.dataset.historyDate)))
      .forEach((row) => list.append(row));
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-chart-date], [data-chart-type]")) updateBuyerChart();
    if (event.target.matches("[data-watchlist-category], [data-watchlist-sort]")) paintWatchlist();
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-watchlist-action]");
    if (!button) return;
    const row = button.closest("[data-watchlist-row]");
    const status = row?.querySelector("[data-watchlist-status]");
    if (!row || !status) return;
    if (button.dataset.watchlistAction === "remove") {
      const saved = readWatchlist();
      saved.delete(row.dataset.listingId);
      try { localStorage.setItem(WATCHLIST_KEY, JSON.stringify([...saved])); } catch { /* Session-only fallback. */ }
      paintWatchlist();
    } else if (button.dataset.watchlistAction === "message") {
      status.textContent = "Messaging UI is not connected yet. The existing conversation model will power this action.";
    } else {
      status.textContent = "Bundle selection UI is not connected yet. Existing Bundle and BundleItem records will power this action.";
    }
  });

  document.addEventListener("dashboard:content-loaded", () => {
    paintWatchlist();
    updateBuyerChart();
  });
  window.addEventListener("storage", (event) => {
    if (event.key === WATCHLIST_KEY || event.key === null) paintWatchlist();
  });
  paintWatchlist();
  updateBuyerChart();
}
