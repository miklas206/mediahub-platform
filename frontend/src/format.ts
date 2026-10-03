import { getLocale, t } from "./i18n";

export function bytes(value: number | null | undefined): string {
  if (value == null) return "—";
  const units = ["B", "KiB", "GiB"];
  if (value < 1024) return `${Math.round(value)} ${units[0]}`;
  const number = (v: number) =>
    v.toLocaleString(getLocale(), {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
      useGrouping: false,
    });
  if (value < 1024 ** 2) return `${number(value / 1024)} ${units[1]}`;
  if (value < 1024 ** 3) return `${number(value / 1024 ** 2)} MiB`;
  return `${number(value / 1024 ** 3)} GiB`;
}
export function uptime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  return hours >= 24
    ? t("{days}d {hours}h", { days: Math.floor(hours / 24), hours: hours % 24 })
    : t("{hours}h {minutes}m", {
        hours,
        minutes: Math.floor((seconds % 3600) / 60),
      });
}

export function fileFormat(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 && dot < name.length - 1
    ? name.slice(dot + 1).toUpperCase()
    : "No extension";
}
