export function setupBundleStartLauncher() {
  const trigger = document.querySelector("[data-bundle-modal-trigger]");
  if (!trigger) return;

  trigger.addEventListener("click", async (event) => {
    event.preventDefault();

    let dialog = document.querySelector("[data-bundle-start-dialog]");
    if (!dialog) {
      const response = await fetch(trigger.dataset.modalUrl, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) {
        window.location.href = trigger.href;
        return;
      }
      const wrapper = document.createElement("div");
      wrapper.innerHTML = await response.text();
      dialog = wrapper.querySelector("[data-bundle-start-dialog]");
      document.body.appendChild(dialog);
      wireDialog(dialog);
    }
    dialog.showModal();
  });
}

function wireDialog(dialog) {
  const spacePanel = dialog.querySelector('[data-start-panel="space"]');
  const categoryPanels = dialog.querySelectorAll('[data-start-panel="categories"]');

  dialog
    .querySelector("[data-start-close]")
    .addEventListener("click", () => dialog.close());

  dialog.querySelectorAll("[data-space-option]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = dialog.querySelector(
        `[data-space-panel="${button.dataset.spaceOption}"]`
      );
      if (!target) return;
      spacePanel.hidden = true;
      target.hidden = false;
      target.querySelector("h2").focus?.();
    });
  });

  categoryPanels.forEach((panel) => {
    panel.querySelector("[data-start-back]").addEventListener("click", () => {
      panel.hidden = true;
      spacePanel.hidden = false;
    });

    const form = panel.querySelector("[data-start-form]");
    const errorEl = panel.querySelector("[data-start-error]");

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      errorEl.hidden = true;

      const formData = new FormData(form);
      formData.set("space", form.dataset.space);

      const submitButton = form.querySelector('button[type="submit"]');
      submitButton.disabled = true;

      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: formData,
        });
        const data = await response.json();
        if (!response.ok) {
          errorEl.textContent = data.error || "Something went wrong. Try again.";
          errorEl.hidden = false;
          submitButton.disabled = false;
          return;
        }
        window.location.href = data.redirect_url;
      } catch (error) {
        errorEl.textContent = "Something went wrong. Try again.";
        errorEl.hidden = false;
        submitButton.disabled = false;
      }
    });
  });
}
