import embed from "https://esm.sh/vega-embed@6.29.0?deps=vega@5.30.0,vega-lite@5.21.0";

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
