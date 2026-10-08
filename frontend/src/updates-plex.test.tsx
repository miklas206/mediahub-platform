import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { plexUpdateReady, UpdatesPage } from "./updates";
import type { AppInfo } from "./contracts";

const verified = {
  supported: true,
  updateAvailable: true,
  updateSource: "container-image",
  checkStatus: "checked",
  installedVersion: "sha256:" + "a".repeat(64),
  latestVersion: "sha256:" + "b".repeat(64),
};

describe("Plex image update approval", () => {
  it("enables only an explicitly confirmed compatible publisher image update", () => {
    expect(plexUpdateReady(verified)).toBe(true);
  });

  it.each([
    undefined,
    {},
    { ...verified, updateAvailable: false },
    { ...verified, supported: false },
    { ...verified, supported: undefined },
    { ...verified, updateAvailable: undefined },
    { ...verified, updateSource: "plex-server" },
    { ...verified, updateSource: undefined },
    { ...verified, checkStatus: "failed" },
    { ...verified, checkStatus: "deferred" },
    { ...verified, stale: true },
    { ...verified, installedVersion: null },
    { ...verified, latestVersion: null },
    { ...verified, latestVersion: verified.installedVersion },
  ])(
    "disables absent, current, unknown, unsupported or stale results: %j",
    (result) => {
      expect(plexUpdateReady(result)).toBe(false);
    },
  );

  it("starts disabled and keeps explicit app recovery accessible", () => {
    const app: AppInfo = {
      id: "plex",
      name: "Plex",
      packageId: "org.mediahub.plex",
      version: "1.43.4",
      state: "running",
      isMock: false,
      detailPath: "/apps/plex",
      health: { status: "healthy", summary: "OK", lastChecked: "", checks: [] },
    };
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <UpdatesPage apps={[app]} />
      </MemoryRouter>,
    );
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Update Plex<\/button>/);
    expect(html).toContain('href="/apps/plex"');
    expect(html).toContain("Latest publisher image");
    expect(html).toContain(
      "Plex server releases alone do not confirm an image update",
    );
  });
});
