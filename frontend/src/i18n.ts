import { useSyncExternalStore } from "react";
import danish from "./locales/da.json";

export type Language = "en" | "da";
let language: Language = "en";
const listeners = new Set<() => void>();
const translations: Record<string, string> = danish;

export function setLanguage(value: Language) {
  language = value === "da" ? "da" : "en";
  if (typeof document !== "undefined") document.documentElement.lang = language;
  for (const listener of listeners) listener();
}

export function useLanguage() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => language,
    () => "en" as Language,
  );
}

export function getLocale() {
  return language === "da" ? "da-DK" : "en-GB";
}

export function t(
  source: string,
  values: Record<string, string | number> = {},
) {
  const trimmed = source.trim();
  const message =
    language === "da" && translations[trimmed]
      ? source.slice(0, source.length - source.trimStart().length) +
        translations[trimmed] +
        source.slice(source.trimEnd().length)
      : source;
  return message.replace(/\{(\w+)\}/g, (placeholder, key: string) =>
    Object.prototype.hasOwnProperty.call(values, key)
      ? String(values[key])
      : placeholder,
  );
}
