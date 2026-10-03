import { describe, expect, it } from "vitest";
import { orderedIds, readLayouts, readGeometry } from "./page-layout";

describe("page layout preferences", () => {
  it("validates column and card widths from saved browser data", () => {
    for (const value of [
      null,
      "bad",
      "null",
      "[]",
      '{"columns":9,"widths":[]}',
    ])
      expect(readGeometry(value)).toEqual({ columns: 0, widths: {} });
    expect(
      readGeometry(
        '{"columns":3,"widths":{"torrent":0,"feed":2,"invalid":4,"text":"1"}}',
      ),
    ).toEqual({ columns: 3, widths: { torrent: 0, feed: 2 } });
  });
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
