export function setupBrowse({ drawer, favorites }) {
  const results = document.querySelector("[data-results]");
  const form = document.querySelector("[data-filter-form]");
  const searchForm = document.querySelector("[data-search-form]");
  const search = document.querySelector("#search");
  const sort = document.querySelector("#id_sort");
  const status = document.querySelector("[data-browse-status]");
  let controller, timer, view = "grid";
  const mapping = JSON.parse(document.querySelector("#item-type-categories").textContent);
  function syncTypes() {
    const selected = [...form.querySelectorAll('[name="category"]:checked')].map(input => input.value);
    mapping.forEach(item => {
      const row = form.querySelector('[data-item-type="' + item.id + '"]');
      row.hidden = selected.length > 0 && !selected.includes(item.category);
      if (row.hidden) row.querySelector("input").checked = false;
    });
  }
  function syncForm(url) {
    const params = new URL(url, location.href).searchParams;
    for (const input of form.elements) {
      if (!input.name) continue;
      if (input.type === "checkbox") input.checked = params.getAll(input.name).includes(input.value);
      else input.value = params.get(input.name) || "";
    }
    search.value = params.get("q") || "";
    sort.value = params.get("sort") || "newest";
    syncTypes();
  }
  function paintView() {
    results.querySelector("[data-listing-grid]").dataset.view = view;
    document.querySelectorAll("[data-view]").forEach(button => {
      if (button.tagName === "BUTTON") button.setAttribute("aria-pressed", String(button.dataset.view === view));
    });
  }
  async function load(url, history = true, close = false) {
    clearTimeout(timer);
    controller?.abort();
    const current = new AbortController();
    controller = current;
    status.textContent = "Updating listings…";
    results.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(url, { signal: current.signal, headers: { "X-Requested-With": "XMLHttpRequest" } });
      if (!response.ok) throw new Error("Request failed");
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      if (current.signal.aborted) return;
      const updated = page.querySelector("[data-results]");
      if (!updated) throw new Error("Missing results");
      results.replaceChildren(...updated.childNodes);
      document.querySelector("[data-form-errors]").replaceChildren(...page.querySelector("[data-form-errors]").childNodes);
      if (history) window.history.pushState({}, "", url);
      paintView(); favorites.refresh();
      status.textContent = "";
      const hasErrors = !!document.querySelector("[data-form-errors] .errorlist");
      if (hasErrors) status.textContent = "Check the filter values and try again.";
      if (close && !hasErrors) drawer.close();
    } catch (error) {
      if (error.name !== "AbortError") status.textContent = "Could not update listings. Submit search or filters to try again.";
    } finally {
      if (controller === current) results.removeAttribute("aria-busy");
    }
  }
  function submit(close = false) {
    form.elements.q.value = search.value;
    const params = new URLSearchParams(new FormData(form));
    for (const [key, value] of [...params]) if (!value) params.delete(key);
    load(location.pathname + (params.size ? "?" + params : ""), true, close);
  }
  form.addEventListener("submit", event => { event.preventDefault(); submit(true); });
  form.addEventListener("change", () => { syncTypes(); submit(); });
  searchForm.addEventListener("submit", event => { event.preventDefault(); submit(); });
  search.addEventListener("input", () => { clearTimeout(timer); controller?.abort(); timer = setTimeout(submit, 250); });
  sort.addEventListener("change", () => submit());
  document.addEventListener("click", event => {
    const link = event.target.closest("[data-filter-link],[data-reset]");
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); syncForm(link.href); load(link.href);
  });
  window.addEventListener("popstate", () => { syncForm(location.href); load(location.href, false); });
  document.querySelector(".view-controls").hidden = false;
  document.querySelectorAll("button[data-view]").forEach(button => button.addEventListener("click", () => { view = button.dataset.view; paintView(); }));
  syncTypes(); paintView();
}

