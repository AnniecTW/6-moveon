(() => {
  const root = document.querySelector("[data-type-suggestions]");
  if (!root) return;
  const title = document.getElementById("id_title");
  const category = document.getElementById("id_category");
  const itemType = document.getElementById("id_item_type");
  const condition = document.getElementById("id_condition");
  const brand = document.getElementById("id_brand");
  const choice = document.getElementById("id_match_choice");
  const status = root.querySelector("[data-suggestions-status]");
  const list = root.querySelector("[data-suggestions-list]");
  const priceResult = root.querySelector("[data-selection-price]");
  let timer;
  let sequence = 0;
  let selecting = false;
  let activeRequest;
  let manualCategory = category?.value || "";
  let manualItemType = itemType?.value || "";

  const filterTypes = () => {
    for (const option of itemType.options) {
      if (!option.value) continue;
      const available = !category.value || option.dataset.categoryId === category.value;
      option.hidden = !available;
      option.disabled = !available;
    }
    if (itemType.selectedOptions[0]?.disabled) {
      itemType.value = "";
      itemType.dispatchEvent(new Event("change", { bubbles: true }));
    }
  };

  const addOption = (labelText, value, detail) => {
    const label = document.createElement("label");
    label.className = "type-candidate";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "type-candidate-choice";
    radio.value = value;
    radio.checked = choice.value === value;
    radio.addEventListener("change", () => {
      choice.value = value;
      priceResult.hidden = true;
      if (value === "NONE") {
        selecting = true;
        category.value = manualCategory;
        filterTypes();
        itemType.value = manualItemType;
        itemType.dispatchEvent(new Event("change", { bubbles: true }));
        selecting = false;
        status.textContent = "No suggestion applied. Your original item type is selected.";
        return;
      }
      selecting = true;
      const candidate = detail;
      category.value = String(candidate.category_id);
      filterTypes();
      itemType.value = String(candidate.item_type_id);
      status.textContent = `Selected ${candidate.item_type}. Checking price evidence…`;
      itemType.dispatchEvent(new CustomEvent("change", {
        bubbles: true,
        detail: { priceGuidePreview: {
          itemTypeId: String(candidate.item_type_id),
          condition: candidate.price_guide_condition,
          brand: candidate.price_guide_brand,
          result: candidate.price_guide,
        } },
      }));
      selecting = false;
    });
    const body = document.createElement("span");
    const heading = document.createElement("strong");
    heading.textContent = labelText;
    heading.title = detail ? `${detail.category} / ${detail.item_type}` : labelText;
    body.append(heading);
    const small = document.createElement("small");
    small.textContent = detail ?
      `${detail.category} · ${detail.observation_count} items · ${detail.limited_evidence ? "limited price evidence" : `Example: ${detail.example_title || "No title"}`}` :
      "Keep the item type you chose above";
    small.title = small.textContent;
    body.append(small);
    label.append(radio, body);
    list.append(label);
  };

  const search = async () => {
    const current = ++sequence;
    activeRequest?.abort();
    activeRequest = new AbortController();
    list.replaceChildren();
    if ((title.value || "").trim().length < 3) {
      status.textContent = "Enter a title to see suggestions.";
      return;
    }
    status.textContent = "Finding similar item types… The first search may load the model.";
    const params = new URLSearchParams({
      title: title.value, category: category.value, item_type: itemType.value,
      condition: condition?.value || "", brand: brand?.value || "",
    });
    try {
      const response = await fetch(`${root.dataset.suggestionsUrl}?${params}`, {
        credentials: "same-origin", signal: activeRequest.signal,
      });
      const result = await response.json();
      if (current !== sequence) return;
      if (!response.ok) throw new Error(result.message || "Search unavailable");
      const candidates = result.candidates || [];
      for (const candidate of candidates) {
        candidate.price_guide_condition = result.price_guide_condition;
        candidate.price_guide_brand = result.price_guide_brand;
        const option = Array.from(itemType.options).find((entry) => entry.value === String(candidate.item_type_id));
        if (!option) continue;
        candidate.category_id = option.dataset.categoryId;
        addOption(candidate.item_type, `TYPE:${candidate.item_type_id}`, candidate);
      }
      addOption("None of these match", "NONE", null);
      status.textContent = candidates.length ? "Choose a match, or keep your own item type." :
        "No similar types found. Keep your own item type or choose None.";
    } catch (error) {
      if (current === sequence) status.textContent = `${error.message}. Choose an item type yourself.`;
    }
  };

  const schedule = () => {
    if (selecting) return;
    sequence += 1;
    activeRequest?.abort();
    choice.value = "";
    priceResult.hidden = true;
    clearTimeout(timer);
    timer = setTimeout(search, 650);
  };
  category?.addEventListener("change", () => {
    filterTypes();
    manualCategory = category.value;
    manualItemType = itemType.value;
    schedule();
  });
  itemType?.addEventListener("change", () => {
    if (!selecting) {
      manualCategory = category.value;
      manualItemType = itemType.value;
    }
    schedule();
  });
  title?.addEventListener("input", schedule);
  document.addEventListener("moveon:price-guide", (event) => {
    if (!choice.value.startsWith("TYPE:") ||
        choice.value !== `TYPE:${event.detail.itemTypeId}`) return;
    const result = event.detail.result;
    priceResult.hidden = false;
    priceResult.classList.toggle("is-limited", Boolean(result?.warning));
    if (result?.suggested_listing_price) {
      const floor = document.getElementById("id_minimum_price");
      const belowFloor = floor?.value && Number(floor.value) > Number(result.suggested_listing_price);
      priceResult.textContent = result.warning ?
        `Provisional price reference: $${result.suggested_listing_price}. ${result.warning}${belowFloor ? " It is below your minimum price." : ""}` : belowFloor ?
        `Observed-price guide: $${result.suggested_listing_price}, below your minimum. Set your own price or change the minimum.` :
        `Observed-price guide: $${result.suggested_listing_price} · middle 50%: $${result.range_low}–$${result.range_high} · ${result.evidence_grade} evidence. Use it in the Price section above if you wish.`;
    } else {
      priceResult.textContent = result?.explanation || event.detail.error ||
        "A price guide is unavailable. Set your own price.";
    }
    status.textContent = `Selected ${itemType.selectedOptions[0]?.textContent || "item type"}.`;
  });
  filterTypes();
  if (title?.value) search();
})();
