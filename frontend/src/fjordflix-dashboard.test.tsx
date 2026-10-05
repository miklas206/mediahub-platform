import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import { FjordFlixDashboardCard } from "./fjordflix-dashboard";
import { IntegrationProvider, type Integration } from "./integrations";
import { ServiceOverview } from "./control-center";
import { fjordHubAppLink } from "./fjordhub-app-link";

const row: Integration = {
  id: "hub",
  name: "FjordHub",
  baseUrl: "https://192.168.1.40:8443",
  enabled: true,
  allowHttp: false,
  tokenConfigured: true,
  lastSuccessfulSync: null,
  nextSync: 0,
  snapshot: {
    status: "offline",
    capabilities: ["docker.resources.read"],
    apps: [
      {
        id: "fjordflix",
        name: "FjordFlix",
        container_count: 1,
        url: "https://192.168.1.40:9234/",
      },
    ],
    fjordflix: {
      ok: true,
      stale: true,
      library_count: 123,
      streams: [{ id: "s" }],
      items: [
        { id: "latest", title: "Newest", poster_id: "latest" },
        { id: "old", title: "Older", poster_id: "../unsafe" },
      ],
    },
  },
};
const render = (value: Integration) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <FjordFlixDashboardCard row={value} />
    </MemoryRouter>,
  );
it("renders a Plex-style dashboard card independent of Docker status with counts, ordered protected posters and stale state", () => {
  const html = render(row);
  expect(html).toContain("plex-service-tile");
  expect(html).toContain("123");
  expect(html).toContain("Active streams");
  expect(html).toContain("stale");
  expect(html.indexOf('title="Newest"')).toBeLessThan(
    html.indexOf('title="Older"'),
  );
  expect(html).toContain("/api/v1/integrations/hub/fjordflix/posters/latest");
  expect(html).not.toContain("posters/../unsafe");
  expect(html).toContain("Poster unavailable");
  expect(html).toContain('href="https://192.168.1.40:9234/"');
});
it("omits disabled, ungranted and absent optional appdata and handles empty/error", () => {
  expect(render({ ...row, enabled: false })).toBe("");
  expect(render({ ...row, tokenConfigured: false })).toBe("");
  expect(render({ ...row, snapshot: { status: "online" } })).toBe("");
  expect(
    render({
      ...row,
      snapshot: {
        ...row.snapshot,
        fjordflix: { ok: true, library_count: 0, items: [], streams: [] },
      },
    }),
  ).toContain("No titles in the library.");
  expect(
    render({
      ...row,
      snapshot: {
        ...row.snapshot,
        fjordflix: { ok: false, error: "App unavailable" },
      },
    }),
  ).toContain("App unavailable");
});
it("places exactly one card in Your apps rather than an empty installed-app message", () => {
  const html = renderToStaticMarkup(
    <MemoryRouter>
      <IntegrationProvider
        value={{
          items: [row],
          error: "",
          loading: false,
          reload: async () => {},
        }}
      >
        <ServiceOverview
          apps={[]}
          reports={{}}
          live={false}
          failed={true}
          dashboard={{}}
        />
      </IntegrationProvider>
    </MemoryRouter>,
  );
  expect(html.match(/fjordflix-service-tile/g)).toHaveLength(1);
  expect(html).not.toContain("No apps installed");
});
it("preserves explicit app URL variants/nondefault ports and makes absent or untrusted addresses explicit management links", () => {
  for (const field of ["url", "local_url", "external_url"])
    expect(
      fjordHubAppLink(row.baseUrl, {
        id: "fjordflix",
        [field]: "https://192.168.1.40:9234/path",
      }),
    ).toEqual({ href: "https://192.168.1.40:9234/path", management: false });
  for (const url of [
    "javascript:alert(1)",
    "https://evil.example:9234/",
    "https://192.168.1.40:8443/",
    "http://192.168.1.40:9234/",
    "https://user:pass@192.168.1.40:9234/",
    "https://192.168.1.40:9234/?token=x",
    "https://192.168.1.40:9234/#token=x",
  ])
    expect(
      fjordHubAppLink(row.baseUrl, { id: "fjordflix", url })?.management,
    ).toBe(true);
  expect(
    fjordHubAppLink(row.baseUrl, { id: "fjordflix", port: 9234 })?.management,
  ).toBe(true);
  expect(fjordHubAppLink(row.baseUrl, { id: "../unsafe" })).toBeNull();
});
