import { describe, expect, it } from "vitest";
import { bytes, uptime } from "./format";
describe("display actual metrics", () => {
  it("does not invent values when data is unavailable", () => {
    expect(bytes(null)).toBe("—");
  });
  it("formats binary storage and uptime", () => {
    expect(bytes(1024 ** 3)).toBe("1.0 GiB");
    expect(uptime(90061)).toBe("1d 1h");
  });
});
