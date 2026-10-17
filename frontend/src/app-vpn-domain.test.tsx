import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppVPNDomainPanel } from "./app-vpn-domain";

vi.mock("./use-data", () => ({ useData: () => ({
  data: { configured: true, enabled: true, zones: [{ id: "zone", name: "example.com" }],
    routes: [
      { packageId: "org.mediahub.plex", zoneId: "zone", label: "plex", hostname: "plex.example.com", httpsVerified: true },
      { packageId: "org.mediahub.jellyfin", zoneId: "zone", label: "movies", hostname: "movies.example.com", httpsVerified: true },
    ] }, reload: vi.fn(),
}) }));

describe("Media server domain settings", () => {
  it("shows the Jellyfin route independently of Plex", () => {
    const html = renderToStaticMarkup(<MemoryRouter><AppVPNDomainPanel appId="jellyfin-install" app="jellyfin" /></MemoryRouter>);
    expect(html).toContain("Jellyfin domain through MediaVPN");
    expect(html).toContain("movies.example.com");
    expect(html).not.toContain("plex.example.com");
  });
  it("keeps the existing Plex panel compatible", () => {
    const html = renderToStaticMarkup(<MemoryRouter><AppVPNDomainPanel appId="plex-install" /></MemoryRouter>);
    expect(html).toContain("Plex domain through MediaVPN");
    expect(html).toContain("plex.example.com");
    expect(html).not.toContain("movies.example.com");
  });
});
