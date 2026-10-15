(() => {
  const explanation = document.querySelector("[data-price-explanation]");
  if (!explanation) return;
  const itemType = document.getElementById("id_item_type");
  const condition = document.getElementById("id_condition");
  const brand = document.getElementById("id_brand");
  const asking = document.getElementById("id_listing_price");
  const floor = document.getElementById("id_minimum_price");
  const decision = document.getElementById("id_pricing_decision");
  const card = document.querySelector("[data-price-suggestion]");
  const button = card?.querySelector("[data-range-target]");
  const range = card?.querySelector("[data-price-range]");
  const warning = document.querySelector("[data-price-warning]");
  const warningText = warning?.querySelector("[data-price-warning-text]");
  const fullLabel = card?.querySelector(".ai-label-full");
  const mediumLabel = card?.querySelector(".ai-label-medium");
  const screenReaderLabel = card?.querySelector(".sr-only");
  const decline = document.querySelector("[data-decline-price]");
  let current = null;
  let requestNumber = 0;

  const publish = (result, error = "") => {
    document.dispatchEvent(new CustomEvent("moveon:price-guide", {
      detail: { itemTypeId: itemType?.value || "", result, error },
    }));
  };

  const applyFloorGuard = () => {
    const tooLow = Boolean(current && floor?.value &&
      Number(floor.value) > Number(current.suggested_listing_price));
    button.disabled = tooLow;
    const baseExplanation = current?.warning ?
      "This is a provisional observed-price reference. You choose the listing price." :
      current?.explanation;
    if (tooLow) {
      explanation.textContent = `${baseExplanation} This reference is below your minimum price, so set your own price or change the minimum.`;
    } else if (current) {
      explanation.textContent = baseExplanation;
    }
    if (current) publish(current);
  };

  const showResult = (result) => {
    explanation.textContent = result.warning ?
      "This is a provisional observed-price reference. You choose the listing price." : result.explanation;
    warning.hidden = !result.warning;
    warningText.textContent = result.warning || "";
    if (!result.suggested_listing_price) {
      publish(result);
      return;
    }
    current = result;
    button.dataset.rangeMidpoint = result.suggested_listing_price;
    const label = result.warning ? "Limited price reference" : "Observed-price recommendation";
    fullLabel.textContent = label;
    mediumLabel.textContent = result.warning ? "Limited guide" : "Price guide";
    screenReaderLabel.textContent = label;
    button.setAttribute("aria-label", `Use ${label.toLowerCase()} of $${result.suggested_listing_price}`);
    const basis = result.method === "TYPE_MEDIAN_UNADJUSTED" ? " · all conditions" : "";
    range.textContent = result.warning ?
      `$${result.suggested_listing_price} · ${result.comparable_count} observed item${result.comparable_count === 1 ? "" : "s"} · VERY LOW evidence` :
      `$${result.suggested_listing_price} · observed middle 50%: $${result.range_low}–$${result.range_high}${basis} · ${result.evidence_grade} evidence`;
    card.hidden = false;
    decline.hidden = false;
    applyFloorGuard();
  };

  const refresh = async (event) => {
    const number = ++requestNumber;
    current = null;
    decision.value = "EDITED";
    card.hidden = true;
    warning.hidden = true;
    warningText.textContent = "";
    decline.hidden = true;
    decline.textContent = "No thanks, I’ll set my price";
    if (!itemType?.value) {
      explanation.textContent = "Choose an item type for a historical price guide.";
      publish(null, explanation.textContent);
      return;
    }
    const preview = event?.detail?.priceGuidePreview;
    if (preview?.result && preview.itemTypeId === itemType.value &&
        preview.condition === (condition?.value || "") && preview.brand === (brand?.value || "")) {
      showResult(preview.result);
      return;
    }
    const query = new URLSearchParams({
      item_type: itemType.value, condition: condition?.value || "", brand: brand?.value || "",
    });
    try {
      const response = await fetch(`${explanation.dataset.pricingUrl}?${query}`, {
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("Price guide unavailable");
      const result = await response.json();
      if (number !== requestNumber) return;
      showResult(result);
    } catch {
      if (number === requestNumber) {
        explanation.textContent = "Price guide unavailable. You can still set your own price.";
        publish(null, explanation.textContent);
      }
    }
  };

  itemType?.addEventListener("change", refresh);
  condition?.addEventListener("change", refresh);
  brand?.addEventListener("change", refresh);
  floor?.addEventListener("input", applyFloorGuard);
  button?.addEventListener("click", () => { if (current) decision.value = "ACCEPTED"; });
  decline?.addEventListener("click", () => {
    decision.value = "DECLINED";
    decline.textContent = "Recommendation declined";
  });
  asking?.addEventListener("input", () => {
    if (decision.value !== "DECLINED") decision.value = "EDITED";
  });
  refresh();
})();
