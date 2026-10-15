import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { AppInfo } from "./contracts";
import { UpdatesPage, platformUpdateReady } from "./updates";

const fixture = vi.hoisted(() => ({
  state: "ready",
  installed: "0.1.1",
  bundled: "0.1.1",
  release: undefined as Record<string, unknown> | undefined,
}));
vi.mock("./phase2", () => ({
  ErrorBox: () => null,
  useLoad: (path: string) => ({
    reload: () => {},
    error: "",
    data:
      path === "/managed-install/prerequisites"
        ? { state: fixture.state }
        : path === "/updates/summary"
          ? {
              items: [
                {
                  id: "seed",
                  installedVersion: fixture.installed,
                  bundledVersion: fixture.bundled,
                  latestVersion: fixture.bundled,
                },
              ],
              notifications: [],
            }
          : path === "/updates/platform"
            ? fixture.release
            : undefined,
  }),
}));

const app: AppInfo = {
  id: "seed",
  name: "MediaSeed",
  packageId: "org.mediahub.mediaseed",
  version: "managed",
  state: "running",
  isMock: false,
  health: {
    status: "healthy",
    summary: "App running",
    lastChecked: "",
    checks: [],
  },
};

describe("Bundled app updates", () => {
  it("shows the verified app version and explains independent delivery", () => {
    fixture.state = "ready";
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <UpdatesPage apps={[app]} />
      </MemoryRouter>,
    );
    expect(html).toContain("0.1.1");
    expect(html).toContain(
      "This app updates independently from MediaHub Core.",
    );
    expect(html).not.toContain("Retry app preparation");
  });
  it("makes failed preparation and its retry action visible without opening details", () => {
    fixture.state = "failed";
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <UpdatesPage apps={[app]} />
      </MemoryRouter>,
    );
    expect(html).toContain(
      "App preparation failed. The installed app may still use older code; its data was preserved.",
    );
    expect(html).toContain("Retry app preparation");
  });
  it("never presents the registry placeholder as an installed version", () => {
    fixture.state = "ready";
    fixture.installed = "managed";
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <UpdatesPage apps={[app]} />
      </MemoryRouter>,
    );
    expect(html).not.toContain(">managed<");
    expect(html).toContain("Not verified");
    fixture.installed = "0.1.1";
  });
  it("does not use preparation to install a newer bundled app", () => {
    fixture.state = "ready";
    fixture.bundled = "0.1.2";
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <UpdatesPage apps={[app]} />
      </MemoryRouter>,
    );
    expect(html).not.toContain("Retry app preparation");
    expect(html).toContain(">Install update<");
    fixture.bundled = "0.1.1";
  });
  it("does not offer Core installation for the already installed commit", () => {
    fixture.release = {
      installReady: true,
      updateAvailable: true,
      installedCommit: "a".repeat(40),
      latestCommit: "a".repeat(40),
      assets: {},
    };
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <UpdatesPage apps={[]} />
      </MemoryRouter>,
    );
    expect(html).not.toContain(">Install update<");
    fixture.release = undefined;
  });
  it("requires a distinct installable Core update", () => {
    const base = {
      installReady: true,
      updateAvailable: true,
      installedCommit: "a",
      latestCommit: "b",
    } as Parameters<typeof platformUpdateReady>[0];
    expect(platformUpdateReady(base)).toBe(true);
    expect(platformUpdateReady({ ...base!, updateAvailable: false })).toBe(
      false,
    );
    expect(platformUpdateReady({ ...base!, installReady: false })).toBe(false);
    expect(platformUpdateReady({ ...base!, latestCommit: "a" })).toBe(false);
  });
});
