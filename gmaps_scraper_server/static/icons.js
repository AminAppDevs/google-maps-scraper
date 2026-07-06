/** Nucleo Glass Icons — loaded from open-source package (nucleoapp.com/svg-glass-icons) */
const ICON_CDN =
  "https://cdn.jsdelivr.net/gh/tinglinzh/nucleo-glass-icons@main/public/icons/index.json";
const ICON_FETCH_MS = 5000;

let iconMap = null;
let iconLoadPromise = null;

const LOCAL_ICONS = {
  trash: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16"/><path d="M9 7V5.5A1.5 1.5 0 0110.5 4h3A1.5 1.5 0 0115 5.5V7"/><path d="M7 7l.75 11.5A1.5 1.5 0 009.25 20h5.5a1.5 1.5 0 001.5-1.5L17 7"/><path d="M10 11v5M14 11v5"/></g></svg>`,
};

export async function loadIcons() {
  if (iconMap) return iconMap;
  if (iconLoadPromise) return iconLoadPromise;
  iconLoadPromise = fetch(ICON_CDN, { signal: AbortSignal.timeout(ICON_FETCH_MS) })
    .then((r) => r.json())
    .then((list) => {
      iconMap = {
        ...Object.fromEntries(list.map((i) => [i.name, i.svg])),
        ...LOCAL_ICONS,
      };
      return iconMap;
    })
    .catch(() => {
      iconMap = { ...LOCAL_ICONS };
      return iconMap;
    });
  return iconLoadPromise;
}

export function icon(name, className = "glass-icon") {
  const svg = LOCAL_ICONS[name] || iconMap?.[name];
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
