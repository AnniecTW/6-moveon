export function setupHeader() {
  const dialog = document.querySelector("[data-header-dialog]");
  const messages = {
    sell: ["Sell an item", "Listing creation is coming next. You'll be able to add photos, set your price, and choose pickup or delivery."],
    messages: ["Messages", "Your buyer and seller conversations will appear here once account sign-in is connected."],
    profile: ["Your profile", "Account sign-in and profile editing are coming next."],
  };
  document.querySelectorAll("[data-header-action]").forEach(button => {
    button.addEventListener("click", () => {
      const [title, message] = messages[button.dataset.headerAction];
      dialog.querySelector("h2").textContent = title;
      dialog.querySelector("p").textContent = message;
      dialog.showModal();
    });
  });
  dialog.querySelector("button").addEventListener("click", () => dialog.close());
}

