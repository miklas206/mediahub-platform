import { useEffect, useSyncExternalStore } from "react";
import "./theme-styles.css";

import { appearanceTokens, readAppearance, type Appearance } from "./appearance-tokens";
export { appearanceTokens, contrastRatio, defaultAppearance, isHexColor, navigationLayouts, readAppearance, themeStyles } from "./appearance-tokens";
export type { Appearance, NavigationLayout, ThemeStyle } from "./appearance-tokens";

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
  root.dataset.navigation = value?.navigation || "sidebar";
  delete root.dataset.look;
  delete root.dataset.appearanceMode;
  delete root.dataset.density;
  delete root.dataset.reducedMotion;
  if (!value) {
    root.dataset.look = "midnight-glass";
    const mode = root.dataset.theme || "dark";
    root.dataset.appearanceMode =
      mode === "light" ||
      (mode === "system" &&
        window.matchMedia("(prefers-color-scheme: light)").matches)
        ? "light"
        : "dark";
    return;
  }
  const mode =
    value.mode && value.mode !== "inherit"
      ? value.mode
      : root.dataset.theme || "dark";
  const dark =
    mode === "dark" ||
    (mode === "system" &&
      !window.matchMedia("(prefers-color-scheme: light)").matches);
  root.dataset.look = value.style || "classic";
  root.dataset.appearanceMode = dark ? "dark" : "light";
  root.dataset.density = value.density || "comfortable";
  root.dataset.reducedMotion = String(value.reducedMotion ?? false);
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
