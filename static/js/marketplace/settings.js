export function setupSellerSettings() {
  if (document.documentElement.dataset.sellerSettingsReady) return;
  document.documentElement.dataset.sellerSettingsReady = "true";

  document.addEventListener("input", (event) => {
    const form = event.target.closest("[data-seller-settings-form]");
    if (!form) return;
    const status = form.querySelector("[data-settings-status]");
    if (status) status.textContent = "You have unsaved seller-setting changes.";
  });

  document.addEventListener("dashboard:content-loaded", () => {
    const status = document.querySelector("[data-settings-status]");
    if (status) status.textContent = "Preferences are ready to edit.";
  });
}
