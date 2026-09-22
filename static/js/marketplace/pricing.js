const strategyNames = {
  maximize: "Maximize Value",
  balanced: "Balanced",
  "sell-before-move": "Sell Before I Move",
};

function openPlanDialog(button) {
  const dialog = document.querySelector("[data-pricing-plan-dialog]");
  if (!dialog || typeof dialog.showModal !== "function") return;
  dialog.querySelector("[data-plan-listing-name]").textContent = button.dataset.listingTitle;
  dialog.querySelector("[data-plan-listing-id]").value = button.dataset.listingId;
  const selected = dialog.querySelector(`[name="strategy"][value="${button.dataset.strategy}"]`);
  if (selected) selected.checked = true;
  dialog.showModal();
}

function updatePlan(form) {
  const listingId = form.querySelector("[data-plan-listing-id]").value;
  const strategy = new FormData(form).get("strategy");
  const trigger = document.querySelector(`[data-manage-plan][data-listing-id="${listingId}"]`);
  if (trigger && strategyNames[strategy]) {
    trigger.dataset.strategy = strategy;
    trigger.closest(".pricing-listing-card").querySelector(".pricing-strategy-summary strong").textContent = strategyNames[strategy];
  }
  form.closest("dialog").close();
}

function handleRecommendation(button) {
  const panel = button.closest(".recommendation-panel");
  const action = button.dataset.pricingAction;
  panel.querySelectorAll("[data-pricing-action]").forEach((control) => {
    control.disabled = true;
  });
  const status = document.createElement("span");
  status.className = "recommendation-feedback";
  status.setAttribute("role", "status");
  status.textContent = action === "accept"
    ? "Recommendation selected — backend price updates are not connected yet."
    : "Current price kept for this preview.";
  panel.querySelector(".recommendation-actions").replaceChildren(status);
}

export function setupSellerPricing() {
  if (document.documentElement.dataset.sellerPricingReady) return;
  document.documentElement.dataset.sellerPricingReady = "true";

  document.addEventListener("click", (event) => {
    const planButton = event.target.closest("[data-manage-plan]");
    if (planButton) openPlanDialog(planButton);

    const actionButton = event.target.closest("[data-pricing-action]");
    if (actionButton) handleRecommendation(actionButton);
  });

  document.addEventListener("submit", (event) => {
    if (event.target.matches("[data-plan-form]")) {
      event.preventDefault();
      if (event.submitter?.value === "save") updatePlan(event.target);
      else event.target.closest("dialog").close();
    }
    if (event.target.matches("[data-selling-preferences]")) {
      event.preventDefault();
      event.target.querySelector("[data-preferences-status]").textContent =
        "Defaults updated for this preview. Account-level persistence is not connected yet.";
    }
  });
}
