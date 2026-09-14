/** Pointer, keyboard and touch access to scene listing previews. */
export function setupHotspots() {
  const root = document.querySelector(".carousel");
  if (!root) return;
  let active = null, timer;
  function close() {
    clearTimeout(timer);
    if (!active) return;
    active.trigger.setAttribute("aria-expanded", "false");
    active.panel.hidden = true;
    active = null;
    root.removeAttribute("data-preview-open");
  }
  function position() {
    if (!active) return;
    const {trigger, panel} = active;
    const rect = trigger.getBoundingClientRect();
    panel.style.maxHeight = "calc(100dvh - 24px)";
    const width = panel.offsetWidth, height = panel.offsetHeight;
    let left, top;
    // Prefer a side with enough room, so opening on hover never moves a link
    // underneath the pointer before a subsequent click reaches the hotspot.
    if (rect.right + width + 24 <= innerWidth) {
      left = rect.right + 12;
      top = Math.min(Math.max(12, rect.top), innerHeight - height - 12);
    } else if (rect.left - width - 12 >= 12) {
      left = rect.left - width - 12;
      top = Math.min(Math.max(12, rect.top), innerHeight - height - 12);
    } else {
      left = Math.min(Math.max(12, rect.left + rect.width / 2 - width / 2), innerWidth - width - 12);
      const above = rect.top - 24, below = innerHeight - rect.bottom - 24;
      if (above >= below) {
        panel.style.maxHeight = Math.max(80, above) + "px";
        top = rect.top - panel.offsetHeight - 12;
      } else {
        panel.style.maxHeight = Math.max(80, below) + "px";
        top = rect.bottom + 12;
      }
    }
    panel.style.left = left + "px";
    panel.style.top = Math.max(12, top) + "px";
  }
  function open(trigger, panel) {
    clearTimeout(timer);
    if (active?.trigger !== trigger) close();
    active = {trigger, panel};
    trigger.setAttribute("aria-expanded", "true");
    panel.hidden = false;
    root.dataset.previewOpen = "true";
    position();
  }
  function deferClose() { clearTimeout(timer); timer = setTimeout(close, 180); }
  document.querySelectorAll("[data-hotspot]").forEach(trigger => {
    const panel = document.getElementById(trigger.getAttribute("aria-controls"));
    // Moving the preview out of the clipped scene keeps it visible at every breakpoint.
    document.body.append(panel);
    trigger.addEventListener("pointerenter", event => { if (event.pointerType !== "touch") open(trigger, panel); });
    trigger.addEventListener("pointerleave", event => { if (event.pointerType !== "touch") deferClose(); });
    trigger.addEventListener("focus", () => open(trigger, panel));
    trigger.addEventListener("click", () => open(trigger, panel));
    panel.addEventListener("pointerenter", () => clearTimeout(timer));
    panel.addEventListener("pointerleave", event => { if (event.pointerType !== "touch") deferClose(); });
    panel.addEventListener("focusin", () => clearTimeout(timer));
    panel.querySelector("[data-close-preview]").addEventListener("click", () => {
      trigger.focus(); close();
    });
    // A keyboard user can Tab directly into the preview despite its body placement.
    trigger.addEventListener("keydown", event => {
      if (event.key === "Tab" && !event.shiftKey && active?.trigger === trigger) {
        event.preventDefault(); panel.querySelector("a").focus();
      }
    });
  });
  document.addEventListener("focusin", event => {
    if (active && event.target !== active.trigger && !active.panel.contains(event.target)) close();
  });
  document.addEventListener("pointerdown", event => {
    if (active && !active.trigger.contains(event.target) && !active.panel.contains(event.target)) close();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && active) { const trigger = active.trigger; trigger.focus(); close(); }
  });
  window.addEventListener("resize", position);
  window.addEventListener("scroll", position, {passive: true});
  root.addEventListener("slidechange", close);
}
