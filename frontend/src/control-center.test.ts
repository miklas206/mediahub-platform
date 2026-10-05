import { describe, expect, it } from "vitest";
import {
  aggregateServiceStatus,
  chartAreaPath,
  chartPath,
  effectiveServiceStatus,
} from "./control-center";
import type { AppInfo } from "./contracts";
import type { Runtime } from "./runtime";

const app: AppInfo = {
  id: "seedbox",
  name: "Seedbox",
  packageId: "org.mediahub.seedbox",
  version: "1",
  state: "running",
  isMock: false,
  health: { status: "healthy", summary: "", lastChecked: "", checks: [] },
};
const report: Runtime = {
  health: "healthy",
  available: true,
  cached: false,
  agentOnline: true,
};

describe("control center service status", () => {
  it("keeps unknown and unhealthy observations visible in aggregate status", () => {
    expect(aggregateServiceStatus([])).toBe("unknown");
    expect(aggregateServiceStatus(["healthy", "unknown"])).toBe("unknown");
    expect(aggregateServiceStatus(["healthy", "healthy"])).toBe("healthy");
    expect(aggregateServiceStatus(["healthy", "degraded"])).toBe("degraded");
    expect(aggregateServiceStatus(["unhealthy", "degraded", "unknown"])).toBe(
      "unhealthy",
    );
  });
  it("uses the latest runtime health instead of an older app list", () => {
    expect(
      effectiveServiceStatus(
        app,
        { failed: false, report: { ...report, health: "degraded" } },
        true,
      ),
    ).toBe("degraded");
    expect(
      effectiveServiceStatus(
        app,
        { failed: false, report: { ...report, health: "critical" } },
        true,
      ),
    ).toBe("unhealthy");
    expect(effectiveServiceStatus(app, undefined, true)).toBe("healthy");
  });
  it("never presents failed, disconnected or unavailable observations as healthy", () => {
    expect(
      effectiveServiceStatus(app, { failed: false, stale: true, report }, true),
    ).toBe("unknown");
    expect(effectiveServiceStatus(app, { failed: true, report }, true)).toBe(
      "unknown",
    );
    expect(
      effectiveServiceStatus(
        app,
        { failed: false, report: { ...report, available: false } },
        true,
      ),
    ).toBe("unknown");
    expect(
      effectiveServiceStatus(
        app,
        { failed: false, report: { ...report, agentOnline: false } },
        true,
      ),
    ).toBe("unknown");
    expect(effectiveServiceStatus(app, { failed: false, report }, false)).toBe(
      "unknown",
    );
    expect(
      effectiveServiceStatus(app, { failed: false, report }, true, true),
    ).toBe("unknown");
  });
  it("does not require an Agent for Core's Cloudflare monitor", () => {
    const cloudflare: Runtime = {
      ...report,
      agentOnline: false,
      cloudflare: {
        configured: true,
        status: "healthy",
        checkedAt: 1,
        metricsReachable: true,
        connections: 4,
        message: "",
        routes: [],
      },
    };
    expect(
      effectiveServiceStatus(app, { failed: false, report: cloudflare }, true),
    ).toBe("healthy");
    expect(
      effectiveServiceStatus(
        app,
        { failed: false, report: { ...cloudflare, available: false } },
        true,
      ),
    ).toBe("unknown");
  });
});

describe("resource chart data", () => {
  const sample = (at: number, cpu: number | null) => ({
    at,
    cpu,
    ram: 30,
    down: 100,
    up: 20,
  });
  it("fills separate observed segments without bridging missing samples", () => {
    expect(
      chartAreaPath(
        [
          sample(0, 10),
          sample(1000, 20),
          sample(2000, null),
          sample(3000, 30),
          sample(4000, 40),
        ],
        "cpu",
        100,
      ),
    ).toBe(
      "M2.0,74.4 L72.0,66.8 L72.0,82 L2.0,82 Z M212.0,59.2 L282.0,51.6 L282.0,82 L212.0,82 Z",
    );
    expect(
      chartAreaPath(
        [sample(0, 10), sample(1000, null), sample(2000, 20)],
        "cpu",
        100,
      ),
    ).toBe("");
    expect(chartAreaPath([], "cpu", 100)).toBe("");
  });
  it("breaks the line across unavailable measurements", () => {
    const path = chartPath(
      [
        sample(0, 10),
        sample(1000, 20),
        sample(2000, null),
        sample(3000, 30),
        sample(4000, 40),
      ],
      "cpu",
      100,
    );
    expect(path.match(/M/g)).toHaveLength(2);
    expect(path.match(/L/g)).toHaveLength(2);
    expect(path).not.toMatch(/NaN|Infinity/);
  });
  it("uses elapsed time and skips invalid values without inventing a trend", () => {
    const path = chartPath(
      [sample(0, 10), sample(1000, Number.NaN), sample(4000, 30)],
      "cpu",
      100,
    );
    expect(path).toBe("M2.0,74.4  M282.0,59.2");
    expect(chartPath([], "cpu", 100)).toBe("");
    expect(chartPath([sample(0, null)], "cpu", 100)).toBe("");
  });
});
