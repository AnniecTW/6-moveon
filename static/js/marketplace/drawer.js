export function setupDrawer() {
  const panel = document.querySelector(".filter-panel");
  const opener = document.querySelector("[data-open-filters]");
  if (!panel || !("HTMLDialogElement" in window)) return { close() {} };
  const dialog = document.createElement("dialog");
  dialog.className = "filter-dialog";
  dialog.setAttribute("aria-labelledby", "filter-heading");
  dialog.append(panel);
  document.body.append(dialog);
  opener.hidden = false;
  panel.querySelector("[data-close-filters]").hidden = false;
  opener.addEventListener("click", () => dialog.showModal());
  const close = () => { dialog.close(); };
  panel.querySelector("[data-close-filters]").addEventListener("click", close);
  dialog.addEventListener("click", event => {
    if (event.target === dialog) {
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right) close();
    }
  });
  return { close };
}

