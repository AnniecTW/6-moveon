export function setupBrowse({ drawer, favorites }) {
  const results = document.querySelector("[data-results]");
  const form = document.querySelector("[data-filter-form]");
  const searchForm = document.querySelector("[data-search-form]");
  const search = document.querySelector("#search");
  const searchMode = searchForm.elements.search_mode || null;
  const searchModeToggle = searchForm.querySelector("[data-search-mode-toggle]");
  const searchModeInfo = searchForm.querySelector("[data-search-mode-info]");
  const aiSearchStatus = document.querySelector("[data-ai-search-status]");
  const sort = document.querySelector("#id_sort");
  const currency = document.querySelector("[data-currency-select]");
  const currencyStatus = document.querySelector("[data-currency-status]");
  const currencyApi = document.querySelector("[data-marketplace]")?.dataset.currencyApi;
  const status = document.querySelector("[data-browse-status]");
  if (currency) currency.closest(".currency-label").hidden = false;
  let controller,
    currencyController,
    timer,
    toastTimer,
    view = "grid",
    aiSearchPending = false;
  const mapping = JSON.parse(
    document.querySelector("#item-type-categories").textContent,
  );
  function syncTypes() {
    const selected = [
      ...form.querySelectorAll('[name="category"]:checked'),
    ].map((input) => input.value);
    mapping.forEach((item) => {
      const row = form.querySelector('[data-item-type="' + item.id + '"]');
      row.hidden = selected.length > 0 && !selected.includes(item.category);
      if (row.hidden) row.querySelector("input").checked = false;
    });
  }
  function syncForm(url) {
    const params = new URL(url, location.href).searchParams;
    for (const input of form.elements) {
      if (!input.name) continue;
      if (input.type === "checkbox")
        input.checked = params.getAll(input.name).includes(input.value);
      else input.value = params.get(input.name) || "";
    }
    search.value = params.get("q") || "";
    const selectedMode = params.get("search_mode") || "keyword";
    if (searchMode) searchMode.value = selectedMode;
    if (searchModeToggle) searchModeToggle.checked = selectedMode === "ai";
    if (form.elements.search_mode)
      form.elements.search_mode.value = selectedMode;
    sort.value = params.get("sort") || "newest";
    if (currency) currency.value = params.get("currency") || "USD";
    syncTypes();
  }
  function paintCurrencyPrices(rows, displayCurrency) {
    const byId = new Map(rows.map((row) => [String(row.id), row]));
    const formatter = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: displayCurrency,
    });
    document.querySelectorAll("[data-listing-card]").forEach((card) => {
      const row = byId.get(card.dataset.id);
      card.querySelectorAll("[data-price-kind]").forEach((price) => {
        const amount = displayCurrency === "USD"
          ? price.dataset.usdPrice
          : row?.[price.dataset.priceKind + "_price"];
        if (amount === undefined || amount === null) return;
        price.textContent = price.dataset.priceKind === "listing" && Number(amount) === 0
          ? "Free"
          : formatter.format(Number(amount));
      });
    });
  }
  async function updateCurrencyPrices() {
    if (!currency || !currencyApi) return;
    currencyController?.abort();
    const current = new AbortController();
    currencyController = current;
    const displayCurrency = currency.value;
    const params = new URLSearchParams(location.search);
    params.set("currency", displayCurrency);
    try {
      const response = await fetch(currencyApi + "?" + params.toString(), {
        signal: current.signal,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Conversion failed");
      if (current.signal.aborted) return;
      paintCurrencyPrices(data.results, displayCurrency);
      currencyStatus.textContent = displayCurrency === "USD" || !data.rate_date
        ? ""
        : "Approximate conversion from USD using the " + data.rate_date + " rate.";
    } catch (error) {
      if (error.name === "AbortError") return;
      paintCurrencyPrices([], "USD");
      currencyStatus.textContent = "Conversion unavailable. Prices are shown in USD.";
    }
  }
  function paintView() {
    results.querySelector("[data-listing-grid]").dataset.view = view;
    document.querySelectorAll("[data-view]").forEach((button) => {
      if (button.tagName === "BUTTON")
        button.setAttribute(
          "aria-pressed",
          String(button.dataset.view === view),
        );
    });
  }
  function showAiFallbackToast(root = results) {
    const toast = root.querySelector("[data-ai-search-toast]");
    if (!toast) return;
    if (!toast.open) toast.showModal();
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      if (toast.open) toast.close();
    }, 7000);
    toast.addEventListener("close", () => clearTimeout(toastTimer), { once: true });
    toast.querySelector("[data-ai-search-toast-close]").addEventListener(
      "click",
      () => toast.close(),
      { once: true },
    );
  }
  async function load(url, history = true, close = false) {
    if (aiSearchPending) return;
    clearTimeout(timer);
    controller?.abort();
    const current = new AbortController();
    controller = current;
    const requestUrl = new URL(url, location.href);
    const aiRequest =
      requestUrl.searchParams.get("search_mode") === "ai" &&
      !!requestUrl.searchParams.get("q")?.trim();
    if (aiRequest) {
      aiSearchPending = true;
      searchForm.classList.add("is-loading");
      searchModeInfo?.setAttribute("aria-expanded", "false");
      aiSearchStatus.hidden = true;
      aiSearchStatus.textContent = "";
      [...searchForm.elements, ...form.elements].forEach((element) => {
        element.disabled = true;
      });
    } else {
      aiSearchStatus.hidden = true;
      aiSearchStatus.textContent = "";
    }
    status.textContent = aiRequest ? "" : "Updating listings…";
    results.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(url, {
        signal: current.signal,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) throw new Error("Request failed");
      const page = new DOMParser().parseFromString(
        await response.text(),
        "text/html",
      );
      if (current.signal.aborted) return;
      const updated = page.querySelector("[data-results]");
      if (!updated) throw new Error("Missing results");
      results.replaceChildren(...updated.childNodes);
      showAiFallbackToast();
      document
        .querySelector("[data-form-errors]")
        .replaceChildren(
          ...page.querySelector("[data-form-errors]").childNodes,
        );
      if (history) window.history.pushState({}, "", url);
      paintView();
      favorites.refresh();
      await updateCurrencyPrices();
      status.textContent = "";
      const hasErrors = !!document.querySelector(
        "[data-form-errors] .errorlist",
      );
      if (hasErrors)
        status.textContent = "Check the filter values and try again.";
      if (close && !hasErrors) drawer.close();
    } catch (error) {
      if (error.name !== "AbortError") {
        status.textContent =
          "Could not update listings. Submit search or filters to try again.";
        if (aiRequest) {
          aiSearchStatus.textContent =
            "AI search could not be completed. Check the server and try again.";
          aiSearchStatus.hidden = false;
        }
      }
    } finally {
      if (controller === current) results.removeAttribute("aria-busy");
      if (aiRequest) {
        aiSearchPending = false;
        searchForm.classList.remove("is-loading");
        [...searchForm.elements, ...form.elements].forEach((element) => {
          element.disabled = false;
        });
        if (!aiSearchStatus.textContent.startsWith("AI search could not"))
          aiSearchStatus.hidden = true;
      }
    }
  }
  function submit(close = false) {
    if (aiSearchPending) return;
    form.elements.q.value = search.value;
    const selectedMode = searchModeToggle
      ? searchModeToggle.checked ? "ai" : "keyword"
      : searchMode?.value || "keyword";
    if (searchMode) searchMode.value = selectedMode;
    if (form.elements.search_mode)
      form.elements.search_mode.value = selectedMode;
    const params = new URLSearchParams(location.search);
    const formParams = new URLSearchParams(new FormData(form));
    for (const key of new Set(formParams.keys())) params.delete(key);
    for (const [key, value] of formParams) params.append(key, value);
    if (sort) params.set("sort", sort.value);
    if (currency) params.set("currency", currency.value);
    for (const [key, value] of [...params]) if (!value) params.delete(key);
    load(location.pathname + (params.size ? "?" + params : ""), true, close);
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit(true);
  });
  form.addEventListener("change", () => {
    syncTypes();
    submit();
  });
  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submit();
  });
  searchModeToggle?.addEventListener("change", () => submit());
  if (searchModeInfo) {
    searchModeInfo.addEventListener("click", () => {
      if (!window.matchMedia("(hover: none)").matches) return;
      searchModeInfo.setAttribute(
        "aria-expanded",
        String(searchModeInfo.getAttribute("aria-expanded") !== "true"),
      );
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".search-mode-info-wrap"))
        searchModeInfo.setAttribute("aria-expanded", "false");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && searchModeInfo.getAttribute("aria-expanded") === "true") {
        searchModeInfo.setAttribute("aria-expanded", "false");
        searchModeInfo.blur();
      }
    });
  }
  search.addEventListener("input", () => {
    if (searchModeToggle?.checked || searchMode?.value === "ai") return;
    clearTimeout(timer);
    controller?.abort();
    timer = setTimeout(submit, 250);
  });
  sort.addEventListener("change", () => submit());
  currency?.addEventListener("change", () => {
    const next = new URL(location.href);
    next.searchParams.set("currency", currency.value);
    window.history.pushState({}, "", next);
    updateCurrencyPrices();
  });
  document.addEventListener("click", (event) => {
    const link = event.target.closest("[data-filter-link],[data-reset]");
    if (
      !link ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    syncForm(link.href);
    load(link.href);
  });
  window.addEventListener("popstate", () => {
    syncForm(location.href);
    load(location.href, false);
  });
  document.querySelector(".view-controls").hidden = false;
  document.querySelectorAll("button[data-view]").forEach((button) =>
    button.addEventListener("click", () => {
      view = button.dataset.view;
      paintView();
    }),
  );
  syncTypes();
  paintView();
  showAiFallbackToast();
  updateCurrencyPrices();
}
