import type { Runtime } from "./runtime";

export function appStatusLabel(status: string) {
  return (
    (
      {
        healthy: "Healthy",
        degraded: "Warning",
        unhealthy: "Critical",
        critical: "Critical",
        offline: "Offline",
      } as Record<string, string>
    )[status] || "Unknown"
  );
}

export function seedboxStatus(r: Runtime): { label: string; message?: string } {
  if (!r.available || !r.agentOnline)
    return {
      label: "Status unavailable",
      message:
        "Cannot reach the Agent. The current VPN and torrent status cannot be verified.",
    };
  if (r.control?.operation.state === "running")
    return {
      label: "Working",
      message:
        r.control.operation.message ||
        "A runtime operation is in progress. Torrent connections may pause while safety checks run.",
    };
  const blocked = r.control?.manualIntervention || [];
  if (blocked.length)
    return {
      label: "Action required",
      message: `Automatic recovery is paused after repeated failures: ${blocked.join(", ")}. Review VPN and storage checks, then use Start Seedbox in Settings to retry safely.`,
    };
  if (r.control?.desiredRunning === false)
    return {
      label: "Stopped",
      message:
        "Seedbox is set to stay stopped. Use Start Seedbox in Settings when you want it to run.",
    };
  if (r.storage?.mounted === false || r.storage?.appWritable === false)
    return {
      label: "Storage unavailable",
      message:
        "The download storage is missing or not writable. Torrent operation is blocked until storage checks pass.",
    };
  if (!r.vpn?.verified)
    return {
      label: "VPN not verified",
      message:
        "The VPN connection has not passed verification. qBittorrent cannot safely start until the VPN checks pass.",
    };
  if (!r.qBittorrent?.healthy && r.qBittorrent?.oomKilled) {
    return {
      label: "Memory limit reached",
      message: `Docker reports that qBittorrent was killed after exceeding its memory limit. Current limit: ${r.qBittorrent.memoryLimitMiB || "unknown"} MiB. Check memory allocation before retrying.`,
    };
  }
  if (!r.qBittorrent?.healthy)
    return {
      label: r.qBittorrent?.running
        ? "Torrent checks failed"
        : "qBittorrent stopped",
      message:
        r.portForwarding?.lastError ||
        "qBittorrent is stopped or has not passed its connection checks. Review VPN and runtime controls for recovery.",
    };
  if (r.health !== "healthy")
    return {
      label: appStatusLabel(r.health),
      message:
        r.portForwarding?.lastError ||
        "Some runtime checks have not passed. Review the VPN and storage status.",
    };
  return { label: "Healthy" };
}
