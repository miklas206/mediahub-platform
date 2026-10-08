import { Globe2 } from "lucide-react";
import { getLocale, useLanguage } from "./i18n";
import "./country-flag.css";

const codes = new Set(
  "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW XK".split(
    " ",
  ),
);
const normalize = (name: string) =>
  name
    .trim()
    .replace(/[_-]/g, " ")
    .replace(/\s+/g, " ")
    .toLocaleLowerCase("en");
const names = new Map<string, string>();
for (const locale of ["en", "da"]) {
  const display = new Intl.DisplayNames([locale], { type: "region" });
  for (const code of codes) {
    const name = display.of(code);
    if (name) names.set(normalize(name), code);
  }
}
Object.entries({
  "united states": "US",
  "united states of america": "US",
  usa: "US",
  "united kingdom": "GB",
  uk: "GB",
  "south korea": "KR",
  "north korea": "KP",
  "czech republic": "CZ",
  turkey: "TR",
  taiwan: "TW",
  russia: "RU",
  vietnam: "VN",
  moldova: "MD",
}).forEach(([name, code]) => names.set(name, code));

/** Resolve only supported regions; unknown input must never display an arbitrary flag. */
export function countryCode(value?: string | null): string | undefined {
  if (!value) return undefined;
  const code = value.trim().toUpperCase();
  return codes.has(code) ? code : names.get(normalize(value));
}

/** Display an ISO code or API country name in the account's current language. */
export function countryLabel(value: string): string {
  const code = countryCode(value);
  return code
    ? new Intl.DisplayNames([getLocale()], { type: "region" }).of(code) || value
    : value;
}

export function CountryFlag({
  code,
  country,
  size = 26,
  decorative = false,
  className = "",
}: {
  code?: string | null;
  country?: string | null;
  /** Width in pixels; country flags keep a consistent 4:3 shape. */
  size?: number;
  decorative?: boolean;
  className?: string;
}) {
  useLanguage();
  const resolved = countryCode(code) || countryCode(country);
  const label = countryLabel(resolved || country || code || "");
  return resolved ? (
    <img
      className={`country-flag ${className}`.trim()}
      src={`/assets/flags/${resolved.toLowerCase()}.svg`}
      alt={decorative ? "" : label}
      title={label}
      width={size}
      height={size * 0.75}
      loading="lazy"
      decoding="async"
    />
  ) : (
    <Globe2
      className={`country-flag country-flag-unknown ${className}`.trim()}
      aria-hidden={decorative || !label ? true : undefined}
      aria-label={decorative || !label ? undefined : label}
      role={decorative || !label ? undefined : "img"}
      size={size}
      strokeWidth={1.75}
    />
  );
}
