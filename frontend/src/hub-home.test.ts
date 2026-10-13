import { describe, expect, it } from "vitest";
import { buildHubEntries, themedAppUrl } from "./hub-home";
import type { AppInfo } from "./contracts";
import type { CatalogApp } from "./phase2-types";
import type { Integration } from "./integrations";

it("passes only the selected theme to independent MediaHub apps without losing their URL", () => {
  const url = new URL(themedAppUrl("https://seed.example/app?view=rss#feeds", "org.mediahub.seedbox", "edge-signal"));
  expect(url.origin).toBe("https://seed.example");
  expect(url.pathname).toBe("/app");
  expect(url.searchParams.get("view")).toBe("rss");
  expect(url.searchParams.get("mediahub_theme")).toBe("edge-signal");
  expect(url.hash).toBe("#feeds");
  expect(themedAppUrl("https://plex.example/", "org.mediahub.plex", "soft-orbit")).toBe("https://plex.example/");
  expect(themedAppUrl("javascript:alert(1)", "org.mediahub.seedbox", "soft-orbit")).toBe("javascript:alert(1)");
});

const catalog = [
  "seedbox",
  "plex",
  "jellyfin",
  "cloudflared",
  "fjordhub",
  "windows-share",
].map((id) => ({
  id: `org.mediahub.${id}`,
  availability: "available",
})) as CatalogApp[];
const seedbox: AppInfo = {
  id: "seedbox-real",
  packageId: "org.mediahub.seedbox",
  name: "Seedbox",
  version: "1",
  state: "running",
  isMock: false,
  detailPath: "/apps/seedbox-real",
  health: {
    status: "healthy",
    summary: "VPN connected",
    lastChecked: "",
    checks: [],
  },
};
const integration: Integration = {
  id: "fjordhub-one",
  name: "FjordHub",
  enabled: true,
  baseUrl: "http://fjordhub.example",
  allowHttp: true,
  tokenConfigured: true,
  snapshot: {
    status: "online",
    apps: [{ id: "fjordflix", name: "FjordFlix", running_count: 1 }],
  },
  lastSuccessfulSync: null,
  nextSync: 0,
};
const input = {
  catalog,
  apps: [] as AppInfo[],
  integrations: [] as Integration[],
  deployment: null,
};

describe("primary MediaHub app hub", () => {
  it("opens a saved external address and keeps app settings accessible", () => {
    const entries = buildHubEntries({ ...input, apps: [{ ...seedbox, externalUrl: "https://seed.example.com" }] });
    expect(entries.find(entry => entry.id === seedbox.packageId)).toMatchObject({ path: "https://seed.example.com", external: true, settingsPath: "/app-settings/org.mediahub.seedbox" });
  });
  it("adds the separate MediaVPN app without claiming tunnel health", () => {
    const entries = buildHubEntries({ ...input, mediavpn: { configured: true, available: true, url: "http://192.168.1.111:18802" } });
    expect(entries.find((entry) => entry.id === "org.mediahub.mediavpn")).toMatchObject({ name: "MediaVPN", path: "http://192.168.1.111:18802/", external: true, configured: true, statusLabel: "App available" });
    expect(buildHubEntries({ ...input, mediavpn: { configured: true, available: true, url: "http://192.168.1.111:18802" }, mediavpnError: "Offline" }).find((entry) => entry.name === "MediaVPN")?.status).toBe("unknown");
    expect(buildHubEntries({ ...input, mediavpn: { configured: true, available: true, url: "javascript:alert(1)" } }).some((entry) => entry.name === "MediaVPN")).toBe(false);
  });
  it("opens the separate MediaSeed instead of the old Seedbox wizard", () => {
    const entries = buildHubEntries({ ...input, mediaseed: { configured: true, available: true, url: "http://192.168.1.111:18800" } });
    expect(entries.find((entry) => entry.id === "org.mediahub.seedbox")).toMatchObject({
      name: "MediaSeed", path: "http://192.168.1.111:18800/", configured: true, external: true, action: "Open app", statusLabel: "App available",
    });
  });
  it("keeps the configured app link without inventing healthy status on failed refresh", () => {
    const entries = buildHubEntries({ ...input, mediaseed: { configured: true, available: true, url: "http://192.168.1.111:18800" }, mediaseedError: "Offline" });
    expect(entries.find((entry) => entry.id === "org.mediahub.seedbox")).toMatchObject({ external: true, status: "unknown", statusLabel: "Status unavailable", action: "Open app" });
    expect(buildHubEntries({ ...input, mediaseed: { configured: true, available: false, url: "javascript:alert(1)" } }).find((entry) => entry.id === "org.mediahub.seedbox")?.external).toBeUndefined();
  });
  it("exposes the supported MediaHub apps with real setup paths before installation", () => {
    const entries = buildHubEntries(input);
    expect(entries).toHaveLength(5);
    expect(
      entries.every(
        (entry) => !entry.configured && entry.statusLabel === "Not set up",
      ),
    ).toBe(true);
    expect(entries.find((entry) => entry.name === "Seedbox")?.path).toBe(
      "/apps/install/seedbox",
    );
    expect(entries.find((entry) => entry.name === "Jellyfin")?.path).toBe(
      "/apps/install/jellyfin",
    );
    expect(entries.find((entry) => entry.name === "Cloudflare")?.path).toBe(
      "/store/cloudflare",
    );
  });
  it("uses live registry paths and health and does not treat mock apps as installed", () => {
    const entries = buildHubEntries({
      ...input,
      apps: [
        seedbox,
        {
          ...seedbox,
          id: "plex-mock",
          packageId: "org.mediahub.plex",
          isMock: true,
        },
      ],
    });
    expect(entries[0]).toMatchObject({
      name: "Seedbox",
      configured: true,
      path: "/apps/seedbox-real",
      status: "healthy",
    });
    expect(entries.find((entry) => entry.name === "Plex")?.configured).toBe(
      false,
    );
  });
  it("keeps FjordHub as one peer app and its child apps inside FjordHub", () => {
    const entries = buildHubEntries({ ...input, integrations: [integration] });
    expect(entries).toHaveLength(5);
    expect(entries.find((entry) => entry.name === "FjordHub")).toMatchObject({
      configured: true,
      path: "/integrations/fjordhub-one",
      status: "healthy",
      statusLabel: "Connected",
    });
    expect(entries.some((entry) => entry.name === "FjordFlix")).toBe(false);
    expect(
      buildHubEntries({
        ...input,
        integrations: [{ ...integration, enabled: false }],
      }).find((entry) => entry.name === "FjordHub")?.configured,
    ).toBe(false);
  });
  it("does not turn failed or stale refreshes into healthy or uninstalled claims", () => {
    const entries = buildHubEntries({
      ...input,
      apps: [seedbox],
      appsError: "Offline",
      integrations: [integration],
    });
    expect(entries.find((entry) => entry.name === "Seedbox")).toMatchObject({
      configured: true,
      status: "unknown",
      statusLabel: "Status unavailable",
      path: "/apps/seedbox-real",
    });
    expect(entries.find((entry) => entry.name === "Plex")).toMatchObject({
      statusLabel: "Status unavailable",
      action: "View setup",
    });
    expect(
      buildHubEntries({
        ...input,
        integrations: [
          { ...integration, snapshot: { status: "online", stale: true } },
        ],
      }).find((entry) => entry.name === "FjordHub")?.status,
    ).toBe("unknown");
  });
  it("respects deployment removal and does not publish retired catalog apps", () => {
    const entries = buildHubEntries({
      ...input,
      catalog: [
        ...catalog,
        {
          id: "org.mediahub.radarr",
          availability: "development",
        } as CatalogApp,
      ],
      deployment: { state: "succeeded", uninstall: { state: "removed" } },
    });
    expect(entries).toHaveLength(5);
    expect(entries.find((entry) => entry.name === "FjordHub")?.configured).toBe(
      false,
    );
    expect(
      buildHubEntries({ ...input, deployment: { state: "succeeded" } }).find(
        (entry) => entry.name === "FjordHub",
      ),
    ).toMatchObject({
      configured: true,
      action: "Complete setup",
      statusLabel: "Complete setup",
    });
  });
});


describe("home card removal capability", () => {
  it("offers removal only for an actual supported installation", () => {
    const statuses = {
      mediaseed: { configured: true, available: true, url: "https://seed.example" },
      mediavpn: { configured: true, available: true, url: "https://vpn.example" },
    };
    const managed = ["mediaseed", "mediavpn"].map(id => ({ ...seedbox, id: `managed-${id}`, name: id, packageId: `org.mediahub.${id}`, removable: true }));
    const entries = buildHubEntries({ ...input, ...statuses, apps: managed });
    expect(entries.filter(entry => entry.removableApp).map(entry => entry.removableApp?.id).sort()).toEqual(["managed-mediaseed", "managed-mediavpn"]);
    expect(buildHubEntries({ ...input, ...statuses }).every(entry => !entry.removableApp)).toBe(true);
    expect(buildHubEntries({ ...input, ...statuses, apps: managed.map(app => ({ ...app, isMock: true })) }).every(entry => !entry.removableApp)).toBe(true);
    expect(buildHubEntries({ ...input, apps: [{ ...seedbox, removable: true }] }).find(entry => entry.id === seedbox.packageId)?.removableApp?.id).toBe(seedbox.id);
  });
});
