import { describe, expect, it } from "vitest";
import { runtimeIssues } from "./runtime-issues";
import type { Runtime } from "./runtime";
const base = {
  available: true,
  agentOnline: true,
  health: "degraded",
  cached: false,
} as Runtime;
describe("runtime issues", () => {
  it("explains a missing metrics address", () => {
    const r = {
      ...base,
      cloudflare: {
        configured: true,
        metricsReachable: false,
        statusUrlConfigured: false,
        message: "Routes reachable; metrics missing",
        routes: [],
      },
    } as unknown as Runtime;
    expect(runtimeIssues(r, "cloudflare").join(" ")).toContain(
      "address is missing",
    );
    r.cloudflare!.statusUrlConfigured = true;
    expect(runtimeIssues(r, "cloudflare").join(" ")).toContain(
      "cannot be read",
    );
  });
  it("names a failing public route", () => {
    const r = {
      ...base,
      cloudflare: {
        configured: true,
        metricsReachable: true,
        message: "Origin unavailable",
        routes: [
          {
            hostname: "media.example.test",
            reachable: false,
            statusCode: 502,
            message: "Origin unavailable",
          },
        ],
      },
    } as unknown as Runtime;
    expect(runtimeIssues(r, "cloudflare").join(" ")).toContain(
      "media.example.test: Origin unavailable (HTTP 502)",
    );
  });
  it("shows failed checks and hides them when healthy", () => {
    const r = {
      ...base,
      health: "critical",
      checks: [{ name: "storage", status: "critical" }],
      plex: { running: true },
    } as Runtime;
    expect(runtimeIssues(r, "plex")).toContain("Storage: critical.");
    expect(runtimeIssues({ ...r, health: "healthy" }, "plex")).toEqual([]);
  });
  it("does not treat cached checks as current when the agent is unavailable", () => {
    expect(
      runtimeIssues(
        {
          ...base,
          agentOnline: false,
          checks: [{ name: "storage", status: "critical" }],
        },
        "seedbox",
      ),
    ).toEqual([
      "Cannot reach the Agent. Current app health cannot be verified. Check the host connection.",
    ]);
  });
});
