import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { activeUploads, DashboardUploads } from "./dashboard-uploads";
import type { Torrent } from "./torrent-list";
import type { AppInfo } from "./contracts";
import { setLanguage } from "./i18n";
import { LayoutGroup, PageLayout } from "./page-layout";

const torrent: Torrent = {
  hash: "a",
  name: "An upload",
  progress: 1,
  state: "uploading",
  dlspeed: 0,
  upspeed: 1024,
  ratio: 1,
  eta: 0,
  size: 10000,
  actionsAllowed: true,
};
const apps = [
  { id: "seedbox", packageId: "org.mediahub.seedbox" },
] as AppInfo[];
function render(
  data: Parameters<typeof DashboardUploads>[0]["data"],
  installed = apps,
) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <DashboardUploads apps={installed} data={data} />
    </MemoryRouter>,
  );
}
afterEach(() => {
  setLanguage("en");
  vi.unstubAllGlobals();
});

describe("active upload snapshot", () => {
  it("counts actual traffic, including incomplete torrents, sorted by speed without mutating input", () => {
    const items = [
      torrent,
      {
        ...torrent,
        hash: "b",
        progress: 0.4,
        state: "downloading",
        upspeed: 2048,
      },
    ];
    expect(activeUploads(items)).toEqual({
      torrents: [items[1], items[0]],
      count: 2,
      speed: 3072,
    });
    expect(items[0]).toBe(torrent);
  });
  it("excludes stalled/zero, negative, missing and non-finite speeds, paused/stopped stale traffic and errors", () => {
    const speeds = [
      0,
      -1,
      undefined,
      null,
      Number.NaN,
      Number.POSITIVE_INFINITY,
      Number.NEGATIVE_INFINITY,
    ];
    const items = speeds.map(
      (upspeed) => ({ ...torrent, state: "stalledUP", upspeed }) as Torrent,
    );
    items.push(
      ...[
        "pausedUP",
        "stoppedUP",
        "pausedDL",
        "error",
        "missingFiles",
        "unknown",
      ].map((state) => ({ ...torrent, state })),
    );
    expect(activeUploads(items)).toEqual({ torrents: [], count: 0, speed: 0 });
    expect(activeUploads()).toBeUndefined();
  });
  it("renders aggregate count/speed, escaped long names, top five and torrent link", () => {
    const name = "<Long & torrent>".repeat(30);
    const markup = render({
      torrents: Array.from({ length: 7 }, (_, i) => ({
        ...torrent,
        hash: `${i}`,
        name: i === 0 ? name : `Upload ${i}`,
      })),
    });
    expect(markup).toContain("7 uploading");
    expect(markup).toContain("7.0 KiB/s");
    expect(markup).toContain("&lt;Long &amp; torrent&gt;");
    expect(markup).toContain('href="/apps/seedbox?section=torrents"');
    expect(markup.match(/class="dashboard-torrent"/g)).toHaveLength(5);
    expect(markup).toContain("2 more in Seedbox");
  });
  it("distinguishes known zero, loading, unavailable and uninstalled states", () => {
    expect(render({ torrents: [] })).toContain("No active uploads.");
    expect(render({ torrents: [] })).toContain("0 uploading");
    expect(render({})).toContain("— uploading");
    expect(render({})).toContain("Loading torrents…");
    const failed = render({ torrents: [torrent], torrentError: true });
    expect(failed).toContain("— uploading");
    expect(failed).toContain('role="alert"');
    expect(failed).not.toContain("An upload");
    expect(failed).not.toContain("No active uploads.");
    expect(render({}, [])).toContain("Install Seedbox");
  });
  it("translates the card into Danish", () => {
    setLanguage("da");
    const markup = render({ torrents: [] });
    expect(markup).toContain("Aktive uploads");
    expect(markup).toContain("Ingen aktive uploads.");
    expect(markup).toContain("0 uploader");
  });
  it("registers a stable new layout id without replacing existing order, hidden state or size", () => {
    const saved: Record<string, string> = {
      "mediahub.layout.v1:uploads-qa": JSON.stringify({
        "ui-Dashboard-1": [".$storage", ".$torrents"],
      }),
      "mediahub.layout.hidden.v1:uploads-qa": JSON.stringify({
        "ui-Dashboard-1": [".$storage"],
      }),
      "mediahub.layout.size.v1:uploads-qa": JSON.stringify({
        columns: 0,
        widths: { "ui-Dashboard-1:.$torrents": 50 },
        heights: {},
      }),
    };
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => saved[key] || null,
    });
    const markup = renderToStaticMarkup(
      <PageLayout storageKey="uploads-qa">
        <LayoutGroup id="ui-Dashboard-1">
          <div
            className="dashboard-card"
            key="torrents"
            data-layout-title="Ongoing torrents"
          />
          <div
            className="dashboard-card"
            key="uploads"
            data-layout-title="Active uploads"
          />
          <div
            className="dashboard-card"
            key="storage"
            data-layout-title="Storage"
          />
        </LayoutGroup>
      </PageLayout>,
    );
    expect(markup).toContain('data-layout-item=".$uploads"');
    expect(markup).not.toContain('data-layout-title="Storage"');
    expect(markup).toContain("--layout-span:6");
    expect(markup.indexOf('data-layout-title="Ongoing torrents"')).toBeLessThan(
      markup.indexOf('data-layout-title="Active uploads"'),
    );
  });
});
