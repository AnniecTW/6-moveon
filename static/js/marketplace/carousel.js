export function setupCarousel() {
  const root = document.querySelector(".carousel");
  if (!root) return;
  const slides = [...root.querySelectorAll(".bundle-slide")];
  if (!slides.length) return;
  const dots = [...root.querySelectorAll("[data-slide]")];
  const pause = root.querySelector("[data-pause]");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let active = 0, paused = reduced.matches;
  root.querySelector(".carousel-controls").hidden = false;
  root.querySelector(".carousel-dots").hidden = false;
  function show(index) {
    root.dispatchEvent(new Event("slidechange"));
    active = (index + slides.length) % slides.length;
    slides.forEach((slide, i) => { slide.hidden = i !== active; });
    dots.forEach((dot, i) => dot.setAttribute("aria-pressed", String(i === active)));
  }
  function paintPause() {
    pause.textContent = paused ? "▷" : "Ⅱ";
    pause.setAttribute("aria-label", paused ? "Play slideshow" : "Pause slideshow");
  }
  pause.addEventListener("click", () => { paused = !paused; paintPause(); });
  root.querySelector("[data-next]").addEventListener("click", () => show(active + 1));
  root.querySelector("[data-previous]").addEventListener("click", () => show(active - 1));
  dots.forEach((dot, i) => dot.addEventListener("click", () => show(i)));
  reduced.addEventListener("change", () => { paused = reduced.matches; paintPause(); });
  setInterval(() => {
    if (!paused && !document.hidden && !root.hasAttribute("data-preview-open") && !root.matches(":hover") && !root.contains(document.activeElement)) show(active + 1);
  }, 6000);
  show(0); paintPause();
}
