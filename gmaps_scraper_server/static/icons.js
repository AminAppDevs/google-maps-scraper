/** Nucleo Glass Icons — loaded from open-source package (nucleoapp.com/svg-glass-icons) */
const ICON_CDN =
  "https://cdn.jsdelivr.net/gh/tinglinzh/nucleo-glass-icons@main/public/icons/index.json";

let iconMap = null;
let iconLoadPromise = null;

export async function loadIcons() {
  if (iconMap) return iconMap;
  if (iconLoadPromise) return iconLoadPromise;
  iconLoadPromise = fetch(ICON_CDN)
    .then((r) => r.json())
    .then((list) => {
      iconMap = Object.fromEntries(list.map((i) => [i.name, i.svg]));
      return iconMap;
    })
    .catch(() => {
      iconMap = {};
      return iconMap;
    });
  return iconLoadPromise;
}

export function icon(name, className = "glass-icon") {
  const svg = iconMap?.[name];
  if (!svg) return `<span class="icon-fallback" aria-hidden="true">•</span>`;
  return svg.replace("<svg", `<svg class="${className}" aria-hidden="true"`);
}

export function setIcon(el, name) {
  if (!el) return;
  el.innerHTML = icon(name);
}

export async function initIcons(root = document) {
  await loadIcons();
  root.querySelectorAll("[data-icon]").forEach((el) => setIcon(el, el.dataset.icon));
}
