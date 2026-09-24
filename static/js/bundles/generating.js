const screen = document.querySelector("[data-generating]");
if (screen) {
  const bundleId = screen.dataset.bundleId;
  const generateUrl = screen.dataset.generateUrl;
  const csrfToken = screen.dataset.csrfToken;
  const errorEl = screen.querySelector("[data-generating-error]");

  fetch(`${generateUrl}?bundle=${encodeURIComponent(bundleId)}`, {
    method: "POST",
    headers: {
      "X-CSRFToken": csrfToken,
      "X-Requested-With": "XMLHttpRequest",
    },
  })
    .then((response) => {
      if (!response.ok) throw new Error(`Unexpected status ${response.status}`);
      return response.json();
    })
    .then((data) => {
      window.location.href = data.redirect_url;
    })
    .catch(() => {
      if (errorEl) errorEl.hidden = false;
    });
}
