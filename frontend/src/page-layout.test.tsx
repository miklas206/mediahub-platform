import { describe, expect, it } from "vitest";
import { orderedIds, readLayouts } from "./page-layout";

describe("page layout preferences", () => {
  it("recovers from missing, corrupt and incorrectly shaped storage", () => {
    for (const raw of [null, "broken", "null", "[]", '"text"']) {
      expect(readLayouts(raw)).toEqual({});
    }
    expect(readLayouts('{"cards":["apps","storage"],"bad":[7]}')).toEqual({
      cards: ["apps", "storage"],
    });
  });

  it("preserves saved cards while appending newly available cards", () => {
    expect(
      orderedIds(["storage", "apps", "network"], ["apps", "storage"]),
    ).toEqual(["apps", "storage", "network"]);
  });

  it("ignores removed cards and duplicate stored IDs", () => {
    expect(
      orderedIds(["apps", "storage"], ["gone", "storage", "storage", "apps"]),
    ).toEqual(["storage", "apps"]);
  });
});
