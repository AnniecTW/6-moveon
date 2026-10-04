export function setupBundleStartLauncher() {
  // Two triggers point here (the header's "Bundle" link and the homepage
  // hero's "Try it!" button), so every matching element gets wired, not
  // just the first - they share one lazily-fetched, cached dialog.
  const triggers = document.querySelectorAll("[data-bundle-modal-trigger]");
  if (!triggers.length) return;

  triggers.forEach((trigger) => {
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      openDialog(trigger, false);
    });
  });

  // After signing in from the bundle flow, the browser returns here with
  // ?open_bundle=1: reopen the popup once and tidy the address bar.
  const url = new URL(window.location.href);
  if (url.searchParams.get("open_bundle") === "1") {
    url.searchParams.delete("open_bundle");
    window.history.replaceState({}, "", url.pathname + url.search + url.hash);
    openDialog(triggers[0], true);
  }
}

async function openDialog(trigger, returningFromLogin) {
  let dialog = document.querySelector("[data-bundle-start-dialog]");
  if (!dialog) {
    let response;
    try {
      response = await fetch(trigger.dataset.modalUrl, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
    } catch (error) {
      window.location.href = trigger.href;
      return;
    }
    // Signed-out visitors are redirected to the account page, which still
    // comes back as a normal 200 page. Send them to log in, then back here.
    if (response.redirected) {
      if (returningFromLogin) return;
      const login = new URL(response.url);
      const back = new URL(window.location.href);
      back.searchParams.set("open_bundle", "1");
      login.searchParams.set("next", back.pathname + back.search);
      window.location.href = login.toString();
      return;
    }
    if (!response.ok) {
      window.location.href = trigger.href;
      return;
    }
    const wrapper = document.createElement("div");
    wrapper.innerHTML = await response.text();
    dialog = wrapper.querySelector("[data-bundle-start-dialog]");
    if (!dialog) {
      window.location.href = trigger.href;
      return;
    }
    document.body.appendChild(dialog);
    wireDialog(dialog);
  }
  dialog.showModal();
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
