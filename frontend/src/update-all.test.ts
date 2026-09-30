import { describe, expect, it, vi } from "vitest";
import type { AppInfo } from "./contracts";
import { runUpdateAll, updateAllPlan } from "./update-all";
import type { OperationState } from "./operation-progress";

const plex = {
  id: "plex",
  name: "Plex",
  packageId: "org.mediahub.plex",
  isMock: false,
} as AppInfo;
const core = { id: "mediahub-core", name: "Core", updateAvailable: true };
const plexUpdate = { id: "plex", name: "Plex", updateAvailable: true };
const plan = () => updateAllPlan([core, plexUpdate], [plex]);
const pause = async () => {};

describe("Update all", () => {
  it("queues only available supported apps, with Core last", () => {
    const result = updateAllPlan(
      [
        core,
        { id: "seedbox", name: "Seedbox", updateAvailable: true },
        plexUpdate,
        { id: "other", name: "Other", updateAvailable: false },
      ],
      [plex],
    );
    expect(result.tasks.map((task) => task.id)).toEqual([
      "plex",
      "mediahub-core",
    ]);
    expect(result.manual.map((task) => task.id)).toEqual(["seedbox"]);
  });

  it("waits for Plex completion and reconnects without repeating install before Core", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({ supported: true, releaseVersions: ["2"] })
      .mockResolvedValueOnce({ state: "running", message: "Downloading" })
      .mockRejectedValueOnce(Error("offline"))
      .mockResolvedValueOnce({
        report: { operation: { state: "succeeded", message: "Healthy" } },
      })
      .mockResolvedValueOnce({ updateAvailable: true, installReady: true })
      .mockResolvedValueOnce({
        state: "running",
        message: "Building",
        operationId: "new",
      })
      .mockResolvedValueOnce({
        state: "succeeded",
        message: "Old operation",
        operationId: "old",
      })
      .mockResolvedValueOnce({
        state: "succeeded",
        message: "Ready",
        operationId: "new",
        logs: ["Build complete"],
      });
    const states: OperationState[] = [];
    expect(
      await runUpdateAll(plan(), request, (state) => states.push(state), pause),
    ).toEqual({ coreUpdated: true, failed: false });
    expect(request.mock.calls.map((call) => call[0])).toEqual([
      "/apps/plex/update-check",
      "/plex/update",
      "/apps/plex/runtime",
      "/apps/plex/runtime",
      "/updates/platform",
      "/updates/platform/install",
      "/updates/platform/operation",
      "/updates/platform/operation",
    ]);
    expect(states.at(-1)?.status).toBe("success");
    expect(
      states.at(-1)?.steps.every((step) => step.state === "complete"),
    ).toBe(true);
    expect(states.at(-1)?.console?.join("\n")).toContain("Build complete");
  });

  it("stops remaining installations after an app fails", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({ releaseVersions: ["2"] })
      .mockResolvedValueOnce({ state: "running", message: "Downloading" })
      .mockResolvedValueOnce({
        report: {
          operation: { state: "failed", message: "Health check failed" },
        },
      });
    const publish = vi.fn();
    expect(await runUpdateAll(plan(), request, publish, pause)).toEqual({
      coreUpdated: false,
      failed: true,
    });
    expect(request).toHaveBeenCalledTimes(3);
    expect(publish.mock.calls.at(-1)?.[0].steps[1].state).toBe("pending");
  });

  it("skips updates that are no longer available", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({ releaseVersions: [] })
      .mockResolvedValueOnce({ updateAvailable: false });
    expect(await runUpdateAll(plan(), request, vi.fn(), pause)).toEqual({
      coreUpdated: false,
      failed: false,
    });
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("does not install when the update check is inconclusive", async () => {
    const request = vi.fn().mockResolvedValue({ supported: false });
    expect((await runUpdateAll(plan(), request, vi.fn(), pause)).failed).toBe(
      true,
    );
    expect(request).toHaveBeenCalledTimes(1);
  });
});
