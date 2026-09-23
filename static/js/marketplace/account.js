document.querySelectorAll("[data-password-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.passwordToggle);
    if (!input) return;
    const visible = input.type === "password";
    input.type = visible ? "text" : "password";
    button.setAttribute("aria-label", visible ? "Hide password" : "Show password");
    button.setAttribute("aria-pressed", String(visible));
  });
});

const googleButton = document.querySelector("[data-google-signin]");
if (googleButton) {
  window.addEventListener("load", () => {
    if (!window.google?.accounts?.id) {
      googleButton.textContent = "Google sign-in is unavailable right now.";
      return;
    }
    window.google.accounts.id.initialize({
      client_id: googleButton.dataset.clientId,
      callback: async ({ credential }) => {
        const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value;
        try {
          const body = new URLSearchParams({ credential });
          const response = await fetch(googleButton.dataset.url, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrf },
            body,
          });
          if (response.redirected) {
            window.location.assign(response.url);
            return;
          }
          const page = new DOMParser().parseFromString(await response.text(), "text/html");
          const message = page.querySelector(".account-errors")?.textContent?.trim() ||
            "Google sign-in could not be completed.";
          googleButton.parentElement.querySelector(".account-google-error")?.remove();
          const error = document.createElement("p");
          error.className = "account-errors";
          error.classList.add("account-google-error");
          error.setAttribute("role", "alert");
          error.textContent = message;
          googleButton.after(error);
        } catch {
          googleButton.parentElement.querySelector(".account-google-error")?.remove();
          const error = document.createElement("p");
          error.className = "account-errors account-google-error";
          error.setAttribute("role", "alert");
          error.textContent = "Google sign-in could not be completed. Try again.";
          googleButton.after(error);
        }
      },
    });
    window.google.accounts.id.renderButton(googleButton, {
      theme: "outline", size: "large", text: "continue_with", shape: "pill",
      width: Math.min(360, googleButton.clientWidth),
    });
  });
}
