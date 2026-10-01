import type { Runtime } from "./runtime";

export function runtimeIssues(
  r: Runtime,
  kind: "cloudflare" | "plex" | "seedbox",
): string[] {
  if (r.health === "healthy") return [];
  if (kind === "cloudflare") {
    const c = r.cloudflare;
    if (!c?.configured)
      return [
        "Cloudflare monitoring is not configured. Open tunnel settings to configure monitoring.",
      ];
    const issues = [c.message || "Cloudflare status could not be verified."];
    if (!c.metricsReachable)
      issues.push(
        c.statusUrlConfigured
          ? "The configured connector status endpoint cannot be read. Check the metrics helper and its connection to MediaHub."
          : "The connector status address is missing. Add the private status endpoint in tunnel settings.",
      );
    for (const route of c.routes || []) {
      if (!route.reachable)
        issues.push(
          `${route.hostname}: ${route.message}${route.statusCode ? ` (HTTP ${route.statusCode})` : ""}. Check the origin service and tunnel route.`,
        );
    }
    return issues;
  }
  if (!r.available || !r.agentOnline)
    return [
      "Cannot reach the Agent. Current app health cannot be verified. Check the host connection.",
    ];
  const names: Record<string, string> = {
    storage: "Storage",
    plex: "Plex server",
    vpn: "VPN",
    qbit: "qBittorrent",
    qbittorrent: "qBittorrent",
    docker: "Docker",
  };
  const issues = (r.checks || [])
    .filter((c) => c.status !== "healthy")
    .map((c) => c.message || `${names[c.name] || c.name}: ${c.status}.`);
  for (const device of r.deviceChecks || [])
    if (device.status !== "healthy")
      issues.push(
        device.message || `Storage device ${device.id}: ${device.status}.`,
      );
  if (r.portForwarding?.lastError) issues.push(r.portForwarding.lastError);
  if (kind === "plex" && !r.plex?.running)
    issues.push(
      "Plex is stopped or unavailable. Check its runtime controls and storage.",
    );
  return [
    ...new Set(
      issues.length
        ? issues
        : [
            "Some runtime checks have not passed. Review the connection and storage checks below.",
          ],
    ),
  ];
}
