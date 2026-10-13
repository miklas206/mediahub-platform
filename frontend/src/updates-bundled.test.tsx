import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { AppInfo } from "./contracts";
import { UpdatesPage } from "./updates";

const fixture = vi.hoisted(() => ({ state: "ready" }));
vi.mock("./phase2", () => ({
  ErrorBox: () => null,
  useLoad: (path: string) => ({
    reload: () => {}, error: "",
    data: path === "/managed-install/prerequisites" ? {state: fixture.state}
      : path === "/updates/summary" ? {items: [{id: "seed", installedVersion: "0.1.1", latestVersion: "0.1.1"}], notifications: []}
      : undefined,
  }),
}));

const app: AppInfo = {id: "seed", name: "MediaSeed", packageId: "org.mediahub.mediaseed", version: "managed", state: "running", isMock: false,
  health: {status: "healthy", summary: "App running", lastChecked: "", checks: []}};

describe("Bundled app updates", () => {
  it("shows the verified app version and explains Core delivery", () => {
    fixture.state = "ready";
    const html = renderToStaticMarkup(<MemoryRouter><UpdatesPage apps={[app]} /></MemoryRouter>);
    expect(html).toContain("0.1.1");
    expect(html).toContain("This app is updated automatically with MediaHub Core.");
    expect(html).not.toContain("Retry app preparation");
  });
  it("makes failed preparation and its retry action visible without opening details", () => {
    fixture.state = "failed";
    const html = renderToStaticMarkup(<MemoryRouter><UpdatesPage apps={[app]} /></MemoryRouter>);
    expect(html).toContain("App preparation failed. The installed app may still use older code; its data was preserved.");
    expect(html).toContain("Retry app preparation");
  });
});
