import { describe, expect, it } from "vitest";
import { isFjordHubInstalled } from "./fjordhub-status";

describe("FjordHub installation status", () => {
  it("recognizes a successful installation without a token integration", () => {
    expect(isFjordHubInstalled({ state: "succeeded" })).toBe(true);
    expect(
      isFjordHubInstalled({
        state: "succeeded",
        verification: { state: "stopped" },
      }),
    ).toBe(true);
  });
  it("does not mark absent, incomplete or removed deployments installed", () => {
    for (const state of ["running", "failed", "interrupted"])
      expect(isFjordHubInstalled({ state })).toBe(false);
    expect(isFjordHubInstalled(null)).toBe(false);
    expect(
      isFjordHubInstalled({
        state: "succeeded",
        verification: { state: "removed" },
      }),
    ).toBe(false);
    expect(
      isFjordHubInstalled({
        state: "succeeded",
        uninstall: { state: "removed" },
      }),
    ).toBe(false);
  });
});
