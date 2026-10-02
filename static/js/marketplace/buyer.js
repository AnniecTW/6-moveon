let pendingCancelCard;

function paintWatchlist() {
  const page = document.querySelector("[data-watchlist-page]");
  if (!page) return;
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
    const active = category === "all" || row.dataset.watchlistCategoryValue === category;
    row.hidden = !active;
    row.classList.toggle("is-saved", active);
    visible += Number(active);
  });
  const count = page.querySelector("[data-watchlist-count]");
  if (count) count.textContent = `${visible} saved item${visible === 1 ? "" : "s"}`;
  page.querySelector("[data-watchlist-empty]")?.classList.toggle("is-visible", visible === 0);
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
    if (event.target.matches("[data-watchlist-category], [data-watchlist-sort]")) paintWatchlist();
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-watchlist-action]");
    if (!button) return;
    const row = button.closest("[data-watchlist-row]");
    const status = row?.querySelector("[data-watchlist-status]");
    if (!row || !status) return;
    if (button.dataset.watchlistAction === "remove") {
      status.textContent = "This watchlist entry is stored in your profile and was not changed.";
    } else if (button.dataset.watchlistAction === "message") {
      status.textContent = "Messaging UI is not connected yet. The existing conversation model will power this action.";
    } else {
      status.textContent = "Bundle selection UI is not connected yet. Existing Bundle and BundleItem records will power this action.";
    }
  });

  document.addEventListener("dashboard:content-loaded", () => {
    paintWatchlist();
  });
  paintWatchlist();
}
