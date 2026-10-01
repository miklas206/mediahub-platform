import { describe, expect, it } from "vitest";
import { appStatusLabel, seedboxStatus } from "./seedbox-status";
import type { Runtime } from "./runtime";
const report = {
  available: true,
  agentOnline: true,
  health: "critical",
  cached: false,
  control: {
    desiredRunning: true,
    manualIntervention: ["vpn"],
    operation: { state: "idle", action: null },
    events: [],
  },
} as Runtime;
describe("Seedbox status", () => {
  it("exposes the recovery latch on the main page", () => {
    expect(seedboxStatus(report).label).toBe("Action required");
    expect(seedboxStatus(report).message).toContain("vpn");
  });
  it("does not present stale recovery details as current when offline", () => {
    expect(seedboxStatus({ ...report, available: false }).label).toBe(
      "Status unavailable",
    );
  });
  it("shows an active retry instead of the previous latch", () => {
    expect(
      seedboxStatus({
        ...report,
        control: {
          ...report.control!,
          operation: { state: "running", action: "start" },
        },
      }).label,
    ).toBe("Working");
  });
  it("distinguishes an intentional stop from a VPN failure", () => {
    expect(
      seedboxStatus({
        ...report,
        control: {
          ...report.control!,
          manualIntervention: [],
          desiredRunning: false,
        },
      }).label,
    ).toBe("Stopped");
  });
  it("maps sidebar failures and unknown status explicitly", () => {
    expect(appStatusLabel("unhealthy")).toBe("Critical");
    expect(appStatusLabel("unknown")).toBe("Unknown");
  });
});

it("explains memory kills only while torrent checks fail", () => {
  const r = {
    ...report,
    control: undefined,
    vpn: { verified: true },
    qBittorrent: { healthy: false, oomKilled: true, memoryLimitMiB: 512 },
  } as Runtime;
  expect(seedboxStatus(r).label).toBe("Memory limit reached");
  expect(
    seedboxStatus({
      ...r,
      health: "healthy",
      qBittorrent: { ...r.qBittorrent!, healthy: true },
    }).label,
  ).toBe("Healthy");
});
