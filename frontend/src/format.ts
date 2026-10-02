export function bytes(value: number | null | undefined): string {
  if (value == null) return "—";
  const units = ["B", "KiB", "GiB"];
  if (value < 1024) return `${Math.round(value)} ${units[0]}`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} ${units[1]}`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MiB`;
  return `${(value / 1024 ** 3).toFixed(1)} GiB`;
}
export function uptime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  return hours >= 24
    ? `${Math.floor(hours / 24)}d ${hours % 24}h`
    : `${hours}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function fileFormat(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 && dot < name.length - 1
    ? name.slice(dot + 1).toUpperCase()
    : "No extension";
}
