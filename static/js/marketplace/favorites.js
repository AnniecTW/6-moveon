const KEY = "moveon:favorites";
export function setupFavorites() {
  let saved = new Set(), onlySaved = false;
  function read() {
    try {
      const value = JSON.parse(localStorage.getItem(KEY) || "[]");
      if (Array.isArray(value)) saved = new Set(value.filter(id => typeof id === "string"));
    } catch { /* Keep this session's selections if storage is unavailable. */ }
  }
  read();
  const toggle = document.querySelector("[data-saved-toggle]");
  toggle.hidden = false;
  function refresh() {
    document.querySelector("[data-saved-count]").textContent = saved.size;
    toggle.setAttribute("aria-pressed", String(onlySaved));
    let visible = 0;
    document.querySelectorAll("[data-listing-card]").forEach(card => {
      const button = card.querySelector("[data-favorite-id]");
      const active = saved.has(button.dataset.favoriteId);
      button.hidden = false;
      button.textContent = active ? "♥" : "♡";
      button.setAttribute("aria-pressed", String(active));
      const title = card.querySelector("h3").textContent;
      button.setAttribute("aria-label", (active ? "Unsave " : "Save ") + title);
      card.hidden = onlySaved && !active;
      if (!card.hidden) visible++;
    });
    document.querySelector("[data-saved-empty]").hidden = !onlySaved || visible !== 0;
    if (onlySaved) document.querySelector("[data-result-count]").textContent = visible + " saved listing" + (visible === 1 ? "" : "s");
  }
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-favorite-id]");
    if (!button) return;
    const id = button.dataset.favoriteId;
    saved.has(id) ? saved.delete(id) : saved.add(id);
    try { localStorage.setItem(KEY, JSON.stringify([...saved])); } catch { /* Session-only fallback. */ }
    refresh();
  });
  toggle.addEventListener("click", () => {
    onlySaved = !onlySaved;
    refresh();
    if (!onlySaved) {
      const count = document.querySelectorAll("[data-listing-card]").length;
      document.querySelector("[data-result-count]").textContent = count + " listing" + (count === 1 ? "" : "s");
    }
  });
  window.addEventListener("storage", event => { if (event.key === KEY || event.key === null) { saved = new Set(); read(); refresh(); } });
  refresh();
  return { refresh };
}

