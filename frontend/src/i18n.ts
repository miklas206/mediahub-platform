import { useSyncExternalStore } from "react";
import danish from "./locales/da.json";

export type Language = "en" | "da";
let language: Language = "en";
const listeners = new Set<() => void>();
const translations: Record<string, string> = danish;
const messageTemplates = Object.keys(translations)
  .filter(
    (key) => /\{\w+\}/.test(key) && key.replace(/\{\w+\}/g, "").length >= 12,
  )
  .sort(
    (a, b) =>
      b.replace(/\{\w+\}/g, "").length - a.replace(/\{\w+\}/g, "").length,
  )
  .map((key) => {
    const names: string[] = [];
    const pattern = key
      .split(/(\{\w+\})/g)
      .map((part) => {
        if (/^\{\w+\}$/.test(part)) {
          names.push(part.slice(1, -1));
          return "(.*?)";
        }
        return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      })
      .join("");
    return { key, names, pattern: new RegExp(`^${pattern}$`, "s") };
  });

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
  let translated =
    translations[trimmed] || translations[trimmed.replace(/\s+/g, " ")];
  if (language === "da" && !translated && Object.keys(values).length === 0) {
    for (const template of messageTemplates) {
      const match = template.pattern.exec(trimmed);
      if (match) {
        translated = translations[template.key].replace(
          /\{(\w+)\}/g,
          (placeholder, name: string) => {
            const index = template.names.indexOf(name);
            return index >= 0
              ? translations[match[index + 1]] || match[index + 1]
              : placeholder;
          },
        );
        break;
      }
    }
  }
  const message =
    language === "da" && translated
      ? source.slice(0, source.length - source.trimStart().length) +
        translated +
        source.slice(source.trimEnd().length)
      : source;
  return message.replace(/\{(\w+)\}/g, (placeholder, key: string) =>
    Object.prototype.hasOwnProperty.call(values, key)
      ? String(values[key])
      : placeholder,
  );
}

/** Translate display text at render time; preserve numbers, elements and raw data. */
export function translateText<T>(value: T): T {
  return (typeof value === "string" ? t(value) : value) as T;
}

const regionCodes =
  "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW".split(
    " ",
  );
const englishRegions = new Intl.DisplayNames(["en"], { type: "region" });
const countryCodes = new Map(
  regionCodes.map((code) => [englishRegions.of(code)?.toLowerCase(), code]),
);
Object.entries({
  "united states": "US",
  "united kingdom": "GB",
  "south korea": "KR",
  "czech republic": "CZ",
  turkey: "TR",
  taiwan: "TW",
  russia: "RU",
  vietnam: "VN",
}).forEach(([name, code]) => countryCodes.set(name, code));

export function countryName(name: string): string {
  if (language === "en") return name;
  const code = countryCodes.get(name.replace(/_/g, " ").toLowerCase());
  return code
    ? new Intl.DisplayNames([getLocale()], { type: "region" }).of(code) || name
    : name;
}
