import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { expect, it } from "vitest";
import {
  FjordHubHome,
  IntegrationProvider,
  type Integration,
} from "./integrations";
import { fjordHubAppLink } from "./fjordhub-app-link";
import { ServiceIcon } from "./service-icon";

const row: Integration = {
  id: "hub",
  name: "Private FjordHub",
  enabled: true,
  tokenConfigured: true,
  allowHttp: false,
  baseUrl: "https://192.168.50.20:8443",
  lastSuccessfulSync: null,
  nextSync: 0,
  appLaunchOverrides: { fjordflix: "https://192.168.50.20:9234/movies" },
  snapshot: {
    status: "online",
    capabilities: ["docker.resources.read"],
    apps: [
      {
        id: "fjordflix",
        name: "FjordFlix",
        container_count: 1,
        running_count: 1,
      },
    ],
    metrics: { cpuPercent: 25 },
  },
};

function home(administrator: boolean) {
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={["/integrations/hub"]}>
      <IntegrationProvider
        value={{
          items: [row, { ...row, id: "other", name: "Other integration" }],
          loading: false,
          error: "",
          reload: async () => {},
        }}
      >
        <Routes>
          <Route
            path="/integrations/:integrationId"
            element={
              <FjordHubHome administrator={administrator} username="fixture" />
            }
          />
        </Routes>
      </IntegrationProvider>
    </MemoryRouter>,
  );
}
it("dedicated home isolates records, includes external action/resources/admin launch settings", () => {
  const html = home(true);
  expect(html).toContain("Private FjordHub");
  expect(html).not.toContain("Other integration");
  expect(html).toContain("Open FjordHub");
  expect(html).toContain('href="https://192.168.50.20:9234/movies"');
  expect(html).toContain("25.0%");
  expect(html).toContain("Signed in as");
  expect(html).toContain('value="https://192.168.50.20:9234/movies"');
  expect(html).not.toContain('type="password"');
  const viewer = home(false);
  expect(viewer).toContain("Only administrators");
  expect(viewer).not.toContain('id="launch-hub-fjordflix"');
});
it("override resolver preserves isolation, encoded paths, consent and clear fallback", () => {
  const app = row.snapshot.apps![0];
  expect(fjordHubAppLink(row.baseUrl, app, row.appLaunchOverrides)?.href).toBe(
    "https://192.168.50.20:9234/movies",
  );
  expect(fjordHubAppLink(row.baseUrl, app, {})?.management).toBe(true);
  expect(
    fjordHubAppLink(
      row.baseUrl,
      { ...app, url: "https://192.168.50.20:7777/" },
      {},
    )?.href,
  ).toContain(":7777");
  expect(
    fjordHubAppLink(row.baseUrl, app, {
      fjordflix: "https://192.168.50.20:9000/my%C3%A6movies",
    })?.href,
  ).toContain("my%C3%A6movies");
  for (const url of [
    "https://evil.example/",
    "javascript:alert(1)",
    "https://user:secret@192.168.50.20/",
    "https://192.168.50.20/?token=secret",
    "https://192.168.50.20/%0A",
    "http://192.168.50.20:9000/",
  ])
    expect(
      fjordHubAppLink(row.baseUrl, app, { fjordflix: url })?.management,
    ).toBe(true);
  expect(
    fjordHubAppLink(
      row.baseUrl,
      app,
      { fjordflix: "http://192.168.50.20:9000/" },
      true,
    )?.management,
  ).toBe(false);
});
it("uses verified MIT official artwork and non-logo fallbacks for unlicensed marks", () => {
  expect(renderToStaticMarkup(<ServiceIcon packageId="fjord3d" />)).toContain(
    "/assets/services/fjord3d.png",
  );
  for (const id of [
    "fjordhub",
    "fjordflix",
    "fjordvpn",
    "urban-explorer",
    "fjordlens",
    "fjordparcel",
    "orbitmap",
    "fjordbudget",
  ])
    expect(renderToStaticMarkup(<ServiceIcon packageId={id} />)).toContain(
      `data-brand-fallback="${id}"`,
    );
});

it("uses official local artwork for each container app", () => {
  for (const id of ["jellyfin", "prowlarr", "radarr", "sonarr", "autobrr"])
    for (const packageId of [id, `org.mediahub.${id}`]) {
      const markup = renderToStaticMarkup(<ServiceIcon packageId={packageId} />);
      expect(markup).toContain(`/assets/services/${id}.png`);
      expect(markup).not.toContain("data-brand-fallback");
    }
});
