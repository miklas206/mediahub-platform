import { describe, expect, it } from "vitest";
import { adjacentSetupStep, normalizeSetupStep } from "./wizard-flow";

describe("Core setup without app installation", () => {
  it("continues from network directly to review and returns to network", () => {
    expect(adjacentSetupStep(5, 1)).toBe(7);
    expect(adjacentSetupStep(7, -1)).toBe(5);
    expect(adjacentSetupStep(7, 1)).toBe(8);
    expect(adjacentSetupStep(8, -1)).toBe(7);
  });
  it("resumes an old app-selection draft at review", () => {
    expect(normalizeSetupStep(6)).toBe(7);
    for (const step of [0, 1, 2, 3, 4, 5, 7, 8, 9]) {
      expect(normalizeSetupStep(step)).toBe(step);
    }
  });
});
