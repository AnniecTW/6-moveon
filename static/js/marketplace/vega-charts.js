import embed from "https://cdn.jsdelivr.net/npm/vega-embed@6/+esm";

for (const target of document.querySelectorAll("[data-vega-spec]")) {
  try {
    const response = await fetch(target.dataset.vegaSpec, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`Chart spec request failed: ${response.status}`);
    const spec = await response.json();
    await embed(target, spec, { actions: false, renderer: "svg" });
  } catch {
    target.textContent = "Chart unavailable. Refresh the page to try again.";
    target.setAttribute("role", "status");
  }
}