import { describe, expect, it } from "vitest";
import {
  canMove,
  cardWidthPercentage,
  LayoutGroup,
  orderedIds,
  readLayouts,
  readGeometry,
} from "./page-layout";

describe("page layout preferences", () => {
  it("preserves old column widths while allowing independent percentage widths", () => {
    expect(cardWidthPercentage(1, 2)).toBe(50);
    expect(cardWidthPercentage(2, 3)).toBe(67);
    expect(cardWidthPercentage(3, 2)).toBe(100);
    expect(cardWidthPercentage(0, 3)).toBe(100);
    expect(cardWidthPercentage(-1, 0)).toBe(-1);
    expect(cardWidthPercentage(25, 1)).toBe(25);
    expect(
      readGeometry('{"columns":0,"widths":{"vpn":33,"backup":50,"bad":42}}'),
    ).toEqual({ columns: 0, widths: { vpn: 33, backup: 50 } });
  });
  it("keeps headings, status, navigation and nested page containers fixed", () => {
    function Page() {
      return (
        <header>
          <h1>Seedbox</h1>
        </header>
      );
    }
    for (const node of [
      <header>
        <h1>Seedbox</h1>
      </header>,
      <div className="runtime-observed">Observed now</div>,
      <div>
        <p>Page description</p>
      </div>,
      <nav>Tabs</nav>,
      <Page />,
      <LayoutGroup id="nested">
        <section className="panel" />
      </LayoutGroup>,
      <div className="panel" role="alert">
        Failure
      </div>,
    ]) {
      expect(canMove(node)).toBe(false);
    }
    expect(canMove(<section className="panel" />)).toBe(true);
    expect(canMove(<div className="dashboard-card" />)).toBe(true);
  });
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
