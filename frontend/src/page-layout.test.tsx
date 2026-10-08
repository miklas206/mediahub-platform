import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { runtimeLayoutSection } from "./seedbox-sections";
import {
  canMove,
  cardWidthPercentage,
  LayoutGroup,
  PageLayout,
  orderedIds,
  readLayouts,
  readGeometry,
  snapCardWidth,
  snapCardHeight,
  migrateVPNLayouts,
  migrateVPNGeometry,
} from "./page-layout";

describe("page layout preferences", () => {
  it("uses the same Seedbox layout on first entry and return from VPN", () => {
    expect(runtimeLayoutSection(null, true)).toBe("torrents");
    expect(runtimeLayoutSection("torrents", true)).toBe("torrents");
    expect(runtimeLayoutSection("vpn", true)).toBe("vpn");
    expect(runtimeLayoutSection("settings", true)).toBe("settings");
    expect(runtimeLayoutSection(null, false)).toBe("");
    expect(runtimeLayoutSection("custom", false)).toBe("custom");
  });
  it("unifies nested movement boundaries while retaining prior sizes, hidden cards and fixed headings", () => {
    const saved: Record<string, string> = {
      "mediahub.layout.v1:qa": JSON.stringify({ nested: [".$b", ".$a"] }),
      "mediahub.layout.hidden.v1:qa": JSON.stringify({ nested: [".$b"] }),
      "mediahub.layout.size.v1:qa": JSON.stringify({
        columns: 0,
        widths: { "nested:.$a": 25 },
        heights: { "nested:.$a": 192 },
      }),
    };
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => saved[key] || null,
    });
    try {
      const markup = renderToStaticMarkup(
        <PageLayout storageKey="qa">
          <LayoutGroup id="parent">
            <header>Fixed heading</header>
            <div className="panel" key="intro" data-layout-title="Intro" />
            <LayoutGroup id="nested" className="runtime-panels">
              <div className="panel" key="a" data-layout-title="A" />
              <div className="panel" key="b" data-layout-title="B" />
            </LayoutGroup>
          </LayoutGroup>
        </PageLayout>,
      );
      expect(markup).toContain('data-layout-item="nested/.$a"');
      expect(markup).not.toContain('data-layout-title="B"');
      expect(markup).toContain("--layout-span:3");
      expect(markup).toContain("--layout-height:192px");
      expect(markup.indexOf("Fixed heading")).toBeLessThan(
        markup.indexOf('data-layout-title="Intro"'),
      );
      expect(markup.match(/class="[^"]*layout-group/g)).toHaveLength(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it("preserves VPN card sizes and visibility when combining their groups", () => {
    expect(
      migrateVPNLayouts({ "seedbox-daily-location": [".0"] })[
        "seedbox-vpn-cards"
      ],
    ).toEqual([".$vpn-location"]);
    expect(
      migrateVPNGeometry({
        columns: 0,
        widths: { "seedbox-daily-location:.0": 50 },
        heights: {},
      }).widths["seedbox-vpn-cards:.$vpn-location"],
    ).toBe(50);
    expect(
      migrateVPNLayouts({
        "seedbox-vpn-cards": [],
        "seedbox-daily-location": [".0"],
      })["seedbox-vpn-cards"],
    ).toEqual([]);
  });
  it("preserves old column widths while allowing independent percentage widths", () => {
    expect(cardWidthPercentage(1, 2)).toBe(50);
    expect(cardWidthPercentage(2, 3)).toBe(67);
    expect(cardWidthPercentage(3, 2)).toBe(100);
    expect(cardWidthPercentage(0, 3)).toBe(100);
    expect(cardWidthPercentage(-1, 0)).toBe(-1);
    expect(cardWidthPercentage(25, 1)).toBe(25);
    expect(
      readGeometry('{"columns":0,"widths":{"vpn":33,"backup":50,"bad":46}}'),
    ).toEqual({ columns: 0, widths: { vpn: 33, backup: 50 }, heights: {} });
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
      expect(readGeometry(value)).toEqual({
        columns: 0,
        widths: {},
        heights: {},
      });
    expect(
      readGeometry(
        '{"columns":3,"widths":{"torrent":0,"feed":2,"invalid":4,"text":"1"}}',
      ),
    ).toEqual({ columns: 3, widths: { torrent: 0, feed: 2 }, heights: {} });
  });
  it("snaps dragged sizes to the grid and bounds saved heights", () => {
    expect(snapCardWidth(284, 1184)).toBe(25);
    expect(snapCardWidth(584, 1184)).toBe(50);
    expect(snapCardWidth(10, 1184)).toBe(25);
    expect(snapCardWidth(3000, 1184)).toBe(100);
    expect(snapCardHeight(301)).toBe(312);
    expect(snapCardHeight(0)).toBe(144);
    expect(snapCardHeight(9999)).toBe(2400);
    expect(
      readGeometry(
        '{"heights":{"vpn":312,"bad":313,"huge":9999},"widths":{"vpn":58}}',
      ),
    ).toEqual({ columns: 0, widths: { vpn: 58 }, heights: { vpn: 312 } });
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
