import { useEffect, useSyncExternalStore } from "react";

export type Appearance = {
  accent: string;
  secondary: string;
  background: string;
  depth: number;
};

export const defaultAppearance: Appearance = {
  accent: "#25c9ed",
  secondary: "#797df2",
  background: "#19314c",
  depth: 40,
};
export const isHexColor = (value: string) => /^#[0-9a-f]{6}$/i.test(value);

export function readAppearance(value: unknown): Appearance | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Partial<Appearance>;
  if (
    ![item.accent, item.secondary, item.background].every(
      (color) => typeof color === "string" && isHexColor(color),
    ) ||
    !Number.isInteger(item.depth) ||
    item.depth! < 0 ||
    item.depth! > 100
  )
    return null;
  return {
    accent: item.accent!.toLowerCase(),
    secondary: item.secondary!.toLowerCase(),
    background: item.background!.toLowerCase(),
    depth: item.depth!,
  };
}

const rgb = (hex: string) =>
  [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16));
const hex = (channels: number[]) =>
  `#${channels
    .map((channel) =>
      Math.round(Math.min(255, Math.max(0, channel)))
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
function mix(first: string, second: string, weight: number) {
  const a = rgb(first),
    b = rgb(second);
  return hex(a.map((channel, i) => channel * (1 - weight) + b[i] * weight));
}
function luminance(color: string) {
  const linear = rgb(color).map((channel) => {
    const n = channel / 255;
    return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
  });
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}
export function contrastRatio(first: string, second: string) {
  const a = luminance(first),
    b = luminance(second);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
function readable(
  color: string,
  surface: string,
  dark: boolean,
  minimum = 4.5,
) {
  for (let step = 0; step <= 100; step++) {
    const candidate = mix(color, dark ? "#ffffff" : "#000000", step / 100);
    if (contrastRatio(candidate, surface) >= minimum) return candidate;
  }
  return dark ? "#ffffff" : "#000000";
}

/** Generate a coordinated family of light/dark shades from the chosen base hue. */
function shade(base: string, lightness: number) {
  const [r, g, b] = rgb(base).map((channel) => channel / 255);
  const maximum = Math.max(r, g, b),
    minimum = Math.min(r, g, b);
  const delta = maximum - minimum,
    midpoint = (maximum + minimum) / 2;
  const saturation = delta
    ? Math.min(0.65, delta / (1 - Math.abs(2 * midpoint - 1)))
    : 0;
  const hue = !delta
    ? 0
    : maximum === r
      ? ((g - b) / delta + 6) % 6
      : maximum === g
        ? (b - r) / delta + 2
        : (r - g) / delta + 4;
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const x = chroma * (1 - Math.abs((hue % 2) - 1)),
    m = lightness - chroma / 2;
  const channels =
    hue < 1
      ? [chroma, x, 0]
      : hue < 2
        ? [x, chroma, 0]
        : hue < 3
          ? [0, chroma, x]
          : hue < 4
            ? [0, x, chroma]
            : hue < 5
              ? [x, 0, chroma]
              : [chroma, 0, x];
  return hex(channels.map((channel) => (channel + m) * 255));
}

export function appearanceTokens(
  appearance: Appearance,
  dark: boolean,
): Record<string, string> {
  const level = appearance.depth / 100;
  const base = dark ? 0.03 + level * 0.09 : 0.97 - level * 0.07;
  const background = shade(appearance.background, base);
  const surface = shade(
    appearance.background,
    dark ? base + 0.035 : Math.min(0.995, base + 0.03),
  );
  const raised = shade(
    appearance.background,
    dark ? base + 0.075 : base - 0.035,
  );
  const sidebar = shade(
    appearance.background,
    dark ? base + 0.015 : Math.min(0.995, base + 0.015),
  );
  // Active controls blend their background with the accent itself. Check that
  // pairing as well as plain cards, including very dark or saturated choices.
  let accent = appearance.accent;
  let accentBackground = surface;
  for (let step = 0; step <= 100; step++) {
    accent = mix(appearance.accent, dark ? "#ffffff" : "#000000", step / 100);
    accentBackground = mix(surface, accent, dark ? 0.15 : 0.1);
    if (
      contrastRatio(accent, raised) >= 4.5 &&
      contrastRatio(accent, accentBackground) >= 4.5
    )
      break;
  }
  const limiting =
    luminance(raised) > luminance(accentBackground) === dark
      ? raised
      : accentBackground;
  const secondary = readable(appearance.secondary, limiting, dark);
  const foreground = dark ? "#f3f7ff" : "#112033";
  return {
    "--bg": background,
    "--surface": surface,
    "--panel": surface,
    "--raised": raised,
    "--sidebar": sidebar,
    "--line": shade(appearance.background, dark ? base + 0.16 : base - 0.16),
    "--text": foreground,
    "--muted": readable(dark ? "#96a9c0" : "#53657c", limiting, dark),
    "--accent": accent,
    "--accent-bg": accentBackground,
    "--accent-line": mix(surface, accent, 0.42),
    "--accent-contrast":
      contrastRatio(accent, "#000000") >= contrastRatio(accent, "#ffffff")
        ? "#000000"
        : "#ffffff",
    "--blue": readable(mix(accent, secondary, 0.6), limiting, dark),
    "--indigo": secondary,
  };
}

let saved: Appearance | null = null;
let accountSession = 0;
let pendingSession: number | null = null;
let preview: Appearance | null | undefined;
let appliedKeys: string[] = [];
const listeners = new Set<() => void>();
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function useAppearance() {
  return useSyncExternalStore(
    subscribe,
    () => saved,
    () => null,
  );
}
export function useAppearanceSaving() {
  return useSyncExternalStore(
    subscribe,
    () => pendingSession !== null,
    () => false,
  );
}
/** Keep a single save in flight even if Settings is closed and reopened. */
export function beginAppearanceSave() {
  if (pendingSession !== null) return null;
  pendingSession = accountSession;
  listeners.forEach((listener) => listener());
  return accountSession;
}
export function finishAppearanceSave(session: number) {
  if (pendingSession !== session) return;
  pendingSession = null;
  listeners.forEach((listener) => listener());
}

export function applyAppearance() {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  for (const key of appliedKeys) root.style.removeProperty(key);
  appliedKeys = [];
  const value = preview === undefined ? saved : preview;
  if (!value) return;
  const mode = root.dataset.theme || "dark";
  const dark =
    mode === "dark" ||
    (mode === "system" &&
      !window.matchMedia("(prefers-color-scheme: light)").matches);
  const tokens = appearanceTokens(value, dark);
  for (const [key, color] of Object.entries(tokens))
    root.style.setProperty(key, color);
  appliedKeys = Object.keys(tokens);
}
export function setAppearance(value: unknown) {
  const next = readAppearance(value);
  const changed = JSON.stringify(next) !== JSON.stringify(saved);
  if (changed) saved = next;
  preview = undefined;
  applyAppearance();
  if (changed) listeners.forEach((listener) => listener());
}
/** Authentication boundaries invalidate responses belonging to an older login. */
export function setAccountAppearance(value: unknown) {
  accountSession++;
  pendingSession = null;
  setAppearance(value);
  listeners.forEach((listener) => listener());
}
export function getAppearanceSession() {
  return accountSession;
}
export function applySavedAppearance(value: unknown, session: number) {
  if (session !== accountSession) return false;
  setAppearance(value);
  return true;
}
export function previewAppearance(value: Appearance | null) {
  preview = readAppearance(value);
  applyAppearance();
}
export function clearAppearancePreview() {
  preview = undefined;
  applyAppearance();
}

export function useAppearanceTheme() {
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const observer = new MutationObserver(applyAppearance);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    media.addEventListener("change", applyAppearance);
    applyAppearance();
    return () => {
      observer.disconnect();
      media.removeEventListener("change", applyAppearance);
    };
  }, []);
}
