import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  canStart,
  FjordHubUpdates,
  type AppInfo,
  type UpdateStatus,
} from "./fjordhub-updates";
import { fjordHubAppLink } from "./fjordhub-app-link";
import {
  fjordHubApps,
  installedFjordHubApps,
  type Integration,
} from "./integrations";

const info: AppInfo = {
  id: "fjordflix",
  name: "FjordFlix",
  port: 9234,
  installed: true,
  icon_path: "/static/logos/icons/flix.png",
  permissions: { updates: true, app_data: false },
};
const status: UpdateStatus = {
  app_id: "fjordflix",
  ok: true,
  running: false,
  update_available: true,
  current_rev: "old",
  remote_rev: "new",
};
const row: Integration = {
  id: "hub",
  name: "FjordHub",
  baseUrl: "https://192.168.50.20:8443",
  allowHttp: false,
  enabled: true,
  tokenConfigured: true,
  lastSuccessfulSync: null,
  nextSync: 0,
  snapshot: {
    status: "online",
    app_info: {
      fjordflix: info,
      fjordhub: { ...info, id: "fjordhub", name: "FjordHub", port: 8443 },
    },
    app_info_stale: false,
    updates: { fjordflix: status },
  },
};

describe("FjordHub keyed app-info and explicit updates", () => {
  it("requires explicit fresh permission and confirmed status", () => {
    expect(canStart(info, status, false)).toBe(true);
    expect(canStart(info, status, true)).toBe(false);
    expect(canStart(undefined, status, false)).toBe(false);
    expect(canStart(info, undefined, false)).toBe(false);
    expect(canStart({ ...info, installed: false }, status, false)).toBe(false);
    expect(
      canStart(
        { ...info, permissions: { updates: false, app_data: true } },
        status,
        false,
      ),
    ).toBe(false);
    for (const changed of [
      { running: true },
      { stale: true },
      { update_available: false },
      { ok: false },
    ])
      expect(canStart(info, { ...status, ...changed }, false)).toBe(false);
  });
  it("joins metadata-only hub and child while retaining metrics", () => {
    const merged = fjordHubApps({
      ...row,
      snapshot: {
        ...row.snapshot,
        apps: [{ id: "fjordflix", name: "Old", cpu_percent: 25 }],
      },
    });
    expect(merged.find((app) => app.id === "fjordflix")).toEqual({
      id: "fjordflix",
      name: "FjordFlix",
      cpu_percent: 25,
      port: 9234,
    });
    expect(installedFjordHubApps(row)).toHaveLength(2);
  });
  it("uses validated API ports and authoritative overrides", () => {
    const app = { id: "fjordflix", port: 9234 };
    expect(fjordHubAppLink(row.baseUrl, app)?.href).toBe(
      "https://192.168.50.20:9234/",
    );
    expect(
      fjordHubAppLink(row.baseUrl, app, {
        fjordflix: "https://192.168.50.20:9999/custom",
      })?.href,
    ).toBe("https://192.168.50.20:9999/custom");
    for (const port of [0, -1, 65536, 1.5, "9234"])
      expect(
        fjordHubAppLink(row.baseUrl, { id: "fjordflix", port })?.management,
      ).toBe(true);
  });
  it("renders Danish acceptance, revisions, no viewer actions and backend-only icons", () => {
    const html = renderToStaticMarkup(
      <FjordHubUpdates
        row={{
          ...row,
          snapshot: {
            ...row.snapshot,
            updates: {
              fjordflix: { ...status, running: true, accepted: true },
            },
          },
        }}
        administrator={false}
      />,
    );
    expect(html).toContain("Start accepteret (202)");
    expect(html).toContain("Installeret revision: old");
    expect(html).not.toContain("<button");
    expect(html).toContain("/api/v1/integrations/hub/apps/fjordflix/icon");
    expect(html).not.toContain("Bearer");
  });
});
