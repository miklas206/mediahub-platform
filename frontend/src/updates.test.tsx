import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { NotificationPopup } from "./notification-popup";
import type { AppInfo } from "./contracts";
import { UpdatesPage } from "./updates";

vi.mock("./notification-popup", () => ({ NotificationPopup: vi.fn(() => null) }));

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
