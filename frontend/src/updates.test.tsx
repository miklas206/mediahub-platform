import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { NotificationPopup } from "./notification-popup";
import type { AppInfo } from "./contracts";
import { UpdatesPage, UpdatesProgress } from "./updates";
import type { OperationState } from "./operation-progress";

vi.mock("./notification-popup", () => ({ NotificationPopup: vi.fn(() => null) }));

const runningUpdate: OperationState = {
  title: "Install MediaHub update",
  status: "running",
  progress: 62,
  message: "Building Core",
  steps: [{ label: "Build services", state: "running" }],
  details: [],
  console: ["Build output"],
};

describe("Updates progress placement", () => {
  it.each([false, true])(
    "keeps active progress above collapsed history, connection lost: %s",
    (connectionLost) => {
      const html = renderToStaticMarkup(
        <div className="stack updates-page">
          <UpdatesProgress operations={{
            all: { ...runningUpdate, title: "Check all updates", status: "success", progress: 100, message: "Checks completed" },
            platform: { ...runningUpdate, connectionLost },
            unused: undefined,
          }} />
        </div>,
      );
      const consoleIndex = html.indexOf('class="updates-console"');
      const active = html.slice(0, consoleIndex);
      const history = html.slice(consoleIndex);
      expect(active).toContain('role="progressbar"');
      expect(active).toContain("62%");
      expect(active).toContain("Build services");
      expect(active).not.toContain("Checks completed");
      expect(history).toContain("Checks completed");
      expect(history).toContain("Build output");
      expect(history).not.toContain('role="progressbar"');
      expect(history).not.toContain("<details open");
      if (connectionLost) {
        expect(active).toContain("Last known progress: 62%. Waiting for connection.");
        expect(active).not.toContain('aria-valuenow=');
      } else {
        expect(active).toContain('aria-valuenow="62"');
      }
    },
  );

  it("moves finished updates into history and leaves no active progress", () => {
    for (const status of ["success", "error", "deferred"] as const) {
      const html = renderToStaticMarkup(
        <UpdatesProgress operations={{ platform: { ...runningUpdate, status } }} />,
      );
      expect(html).not.toContain('role="progressbar"');
      expect(html).toContain("Build output");
      expect(html).not.toContain("<details open");
    }
  });
});

function app(name: string, isMock = false): AppInfo {
  return {
    id: name.toLowerCase().replaceAll(" ", "-"),
    name,
    packageId: "org.mediahub." + name.toLowerCase(),
    version: "1.0",
    state: "running",
    isMock,
    health: { status: "healthy", summary: "OK", lastChecked: "", checks: [] },
  };
}

describe("Updates first render", () => {
  it("shows known app cards before effects or network requests run", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <UpdatesPage
          apps={[
            app("Seedbox"),
            app("Plex"),
            app("Cloudflare Tunnel"),
            app("Mock app", true),
          ]}
        />
      </MemoryRouter>,
    );
    for (const name of [
      "MediaHub Core",
      "Seedbox",
      "Plex",
      "Cloudflare Tunnel",
    ])
      expect(html).toContain(`<h2>${name}</h2>`);
    expect(html).not.toContain("Mock app");
    expect(html.indexOf('class="updates-console"')).toBeLessThan(html.indexOf('class="updates-actions"'));
    expect(html.indexOf('class="updates-console"')).toBeLessThan(html.indexOf('class="updates-components"'));
  });

  it("keeps known cards visible when refreshing the shared list fails", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <UpdatesPage apps={[app("Seedbox")]} appsError="Agent unavailable" />
      </MemoryRouter>,
    );
    expect(html).toContain("<h2>Seedbox</h2>");
    expect(html).not.toContain("Agent unavailable");
    expect(vi.mocked(NotificationPopup).mock.calls.some(([props]) => props.children === "Agent unavailable" && props.tone === "danger")).toBe(true);
  });
});
