import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Apps } from "./ui";
import type { AppInfo } from "./contracts";
import type { Integration } from "./integrations";

const app: AppInfo = {
  id: "plex",
  name: "Plex",
  packageId: "org.mediahub.plex",
  version: "1.0",
  state: "running",
  isMock: false,
  detailPath: "/apps/plex",
  health: { status: "healthy", summary: "Ready", lastChecked: "", checks: [] },
};
const integration: Integration = {
  id: "fjordhub",
  name: "FjordHub",
  baseUrl: "http://192.168.1.40:8888",
  allowHttp: true,
  tokenConfigured: true,
  enabled: true,
  snapshot: { status: "online" },
  lastSuccessfulSync: null,
  nextSync: 0,
};

function render(
  data: AppInfo[] | undefined,
  error = "",
  integrations: Integration[] = [],
) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <Apps
        data={data}
        error={error}
        reload={() => {}}
        integrations={integrations}
      />
    </MemoryRouter>,
  );
}

describe("apps using the shell's live registry", () => {
  it("renders the existing registry immediately without another loading state", () => {
    const html = render([app]);
    expect(html).toContain("Plex");
    expect(html).toContain('href="/apps/plex"');
    expect(html).not.toContain("app-skeleton-grid");
  });
  it("preserves skeleton, empty and failed states", () => {
    expect(render(undefined)).toContain("app-skeleton-grid");
    expect(render([])).toContain("No apps installed");
    expect(render([app], "Offline")).toContain("Offline");
    expect(render([app], "Offline")).toContain("Plex");
  });
  it("retains enabled integration cards even with an empty local registry", () => {
    const html = render([], "", [integration]);
    expect(html).toContain("FjordHub");
    expect(html).toContain('href="http://192.168.1.40:8888"');
    expect(html).not.toContain("No apps installed");
  });
  it("sorts apps without mutating the shared registry", () => {
    const items = [app, { ...app, id: "alpha", name: "Alpha" }];
    const html = render(items);
    expect(html.indexOf("<h2>Alpha")).toBeLessThan(html.indexOf("<h2>Plex"));
    expect(items[0]).toBe(app);
  });
});
