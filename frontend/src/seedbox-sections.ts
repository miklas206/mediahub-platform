export const seedboxSections = [
  ["torrents", "Torrents"],
  ["vpn", "VPN"],
  ["settings", "Settings"],
] as const;
export type SeedboxSection = (typeof seedboxSections)[number][0];
export function seedboxSection(value: string | null): SeedboxSection {
  return value === "vpn" || value === "settings" ? value : "torrents";
}
