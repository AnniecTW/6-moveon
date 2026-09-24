const form = document.querySelector("[data-checkout-form]");
if (form) {
  const sendUrl = form.dataset.sendUrl;
  const csrfToken = form.dataset.csrfToken;
  const submitButton = form.querySelector("[data-checkout-submit]");
  const errorEl = document.querySelector("[data-checkout-error]");

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (errorEl) errorEl.hidden = true;
    submitButton.disabled = true;

    fetch(sendUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken,
        "X-Requested-With": "XMLHttpRequest",
      },
    })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.error || `Unexpected status ${response.status}`);
        }
        window.location.href = data.messagesUrl;
      })
      .catch((error) => {
        submitButton.disabled = false;
        if (errorEl) {
          errorEl.textContent = error.message || "Something went wrong. Please try again.";
          errorEl.hidden = false;
        }
      });
  });
}
