import { describe, expect, it } from "vitest";
import { mediaCapacity } from "./dashboard-data";
import type { Storage } from "./contracts";

const location: Storage = {
  id: "downloads",
  name: "Downloads",
  kind: "downloads",
  path: "/media/downloads",
  exists: true,
  readable: true,
  writable: true,
  totalBytes: 1000,
  freeBytes: 400,
  filesystem: "nfs",
};

describe("dashboard media capacity", () => {
  it("counts shared-filesystem aliases once and adds separate volumes", () => {
    expect(
      mediaCapacity([
        location,
        { ...location, id: "movies", kind: "movies" },
        {
          ...location,
          id: "local",
          filesystem: "ext4",
          totalBytes: 2000,
          freeBytes: 1000,
        },
      ]),
    ).toEqual({
      total: 3000,
      free: 1400,
      used: 1600,
      percent: (1600 / 3000) * 100,
      volumes: 2,
    });
  });
  it("does not turn missing, inaccessible or invalid measurements into capacity", () => {
    expect(mediaCapacity()).toBeUndefined();
    expect(
      mediaCapacity([
        { ...location, exists: false },
        { ...location, readable: false },
        { ...location, kind: "backup" },
        { ...location, error: "Unavailable" },
        { ...location, totalBytes: Number.NaN },
        { ...location, freeBytes: null },
      ]),
    ).toBeUndefined();
    expect(mediaCapacity([{ ...location, freeBytes: 2000 }])?.percent).toBe(0);
  });
});
