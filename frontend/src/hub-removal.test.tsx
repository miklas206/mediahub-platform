import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { HubHome } from "./hub-home";
import { AppSettingsPage } from "./app-settings";
import { setLanguage } from "./i18n";
import type { AppInfo } from "./contracts";

// Static rendering cannot mount a browser portal; inspect its dialog content.
vi.mock("react-dom", () => ({
  createPortal: (children: ReactNode) => children,
}));
afterEach(() => vi.unstubAllGlobals());

vi.mock("./use-data", () => ({
  useData: (path: string) => ({
    data:
      path === "/catalog"
        ? [{ id: "org.mediahub.seedbox", availability: "available" }]
        : path.endsWith("/status")
          ? { configured: true, available: true, url: "https://app.example" }
          : path.startsWith("/app-settings/")
            ? {
                name: "MediaSeed",
                externalUrl: "",
                removableApp: { id: "seed", name: "MediaSeed" },
              }
            : null,
    error: "",
    reload: vi.fn(),
  }),
}));

// Home cards now read the shared page snapshot store rather than useData.
vi.mock("./use-service-snapshot", () => ({
  usePageSnapshot: (path: string) => ({
    data:
      path === "/catalog"
        ? [{ id: "org.mediahub.seedbox", availability: "available" }]
        : path.endsWith("/status")
          ? { configured: true, available: true, url: "https://app.example" }
          : null,
    error: "",
    reload: vi.fn(),
  }),
}));

const app: AppInfo = {
  id: "seed",
  packageId: "org.mediahub.mediaseed",
  name: "MediaSeed",
  version: "1",
  state: "running",
  isMock: false,
  removable: true,
  health: { status: "healthy", summary: "Ready", lastChecked: "", checks: [] },
};

function home(apps: AppInfo[]) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <HubHome
        apps={apps}
        appsError=""
        integrations={[]}
        integrationsError=""
        updates={0}
        live
      />
    </MemoryRouter>,
  );
}

describe("removal on home cards", () => {
  it("renders a red-styled, named removal button beside the app settings", () => {
    setLanguage("da");
    const html = home([app]);
    expect(html).toContain('class="hub-card-uninstall"');
    expect(html).toContain('aria-label="Afinstaller: MediaSeed"');
    expect(html).toContain('aria-label="Indstillinger: MediaSeed"');
    expect(html.match(/class="hub-card-uninstall"/g)).toHaveLength(1);
    expect(html).not.toContain('role="dialog"');
  });

  it("keeps the existing confirmation dialog available for an ongoing removal", () => {
    vi.stubGlobal("document", { body: {} });
    const html = home([{ ...app, state: "removing" }]);
    expect(html).toContain("<dialog");
    expect(html).toContain('disabled=""');
  });

  it("omits removal for connected-only and unsupported apps and from settings", () => {
    expect(home([])).not.toContain('class="hub-card-uninstall"');
    expect(home([{ ...app, removable: false }])).not.toContain(
      'class="hub-card-uninstall"',
    );
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <AppSettingsPage />
      </MemoryRouter>,
    );
    expect(html).not.toContain("Afinstaller");
    expect(html).not.toContain('role="dialog"');
  });
});
