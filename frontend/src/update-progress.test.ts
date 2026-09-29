import { expect, it } from "vitest";
import { disconnectedUpdate, mergeUpdateConsole } from "./update-progress";
import type { OperationState } from "./operation-progress";

const building: OperationState = {
  title: "Install MediaHub update",
  status: "running",
  progress: 62,
  message: "Building core",
  steps: [{ label: "Build on this server", state: "running" }],
  details: ["Version 0.4.19 → 0.4.20"],
  console: ["#1 CACHED"],
};

it("keeps build steps, percentage and console through repeated disconnects", () => {
  const disconnected = disconnectedUpdate(disconnectedUpdate(building));
  expect(disconnected.steps).toEqual(building.steps);
  expect(disconnected.progress).toBe(62);
  expect(disconnected.details).toEqual(building.details);
  expect(disconnected.console).toHaveLength(2);
  const recovered = mergeUpdateConsole(disconnected, {
    ...building,
    progress: 67,
    console: ["#1 CACHED", "#2 DONE"],
  });
  expect(recovered.console).toHaveLength(3);
  expect(recovered.progress).toBe(67);
});

it("shows status messages from older helpers and bounds and redacts history", () => {
  let current: OperationState = { ...building, console: [] };
  for (let i = 0; i < 130; i++)
    current = mergeUpdateConsole(current, {
      ...building,
      message: `step ${i} token=hidden`,
      console: [],
    });
  expect(current.console!).toHaveLength(120);
  expect(current.console!.join("\n")).not.toContain("hidden");
  expect(current.console!.at(-1)).toContain("step 129");
});
