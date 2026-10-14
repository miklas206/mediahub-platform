import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { CloudflareAppRoutes } from "./cloudflare-app-routes";

describe("App domain configuration", () => {
  it("shows only server-provided installed apps and exposes route failures", () => {
    const html = renderToStaticMarkup(
      <CloudflareAppRoutes
        busy={false}
        change={vi.fn()}
        zones={[{ id: "zone", name: "example.com" }]}
        discovered={[]}
        data={{
          apps: [{ packageId: "org.mediahub.jellyfin", name: "Jellyfin" }],
          tunnels: [{ id: "tunnel", name: "Home" }],
          connectors: { tunnel: { state: "stopped" } },
          routes: [
            {
              id: "route",
              hostname: "tv.example.com",
              packageId: "org.mediahub.jellyfin",
              status: "error",
              message: "DNS conflict",
              autoSync: true,
            },
          ],
        }}
      />,
    );
    expect(html).toContain("Jellyfin");
    expect(html).not.toContain("MediaSeed</option>");
    expect(html).toContain("DNS conflict");
    expect(html).toContain("stopped");
    expect(html).toContain("Connect app domain");
  });
  it("cannot publish before a tunnel and domain exist", () => {
    const html = renderToStaticMarkup(
      <CloudflareAppRoutes
        data={{ apps: [] }}
        zones={[]}
        discovered={[]}
        busy={false}
        change={vi.fn()}
      />,
    );
    expect(html).toContain('disabled="">Connect app domain');
  });
});
