import { renderToStaticMarkup as render } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
const renderToStaticMarkup = (node: ReactNode) =>
  render(<MemoryRouter>{node}</MemoryRouter>);
import { expect, it } from "vitest";
import { IntegrationAppLinks, type Integration } from "./integrations";

it("opens local FjordHub overview without linking disconnected or unsafe entries", () => {
  const row: Integration = {
    id: "fjordhub",
    name: "FjordHub",
    baseUrl: "http://192.168.1.40:8888",
    enabled: true,
    tokenConfigured: true,
    allowHttp: true,
    snapshot: { status: "online" },
    lastSuccessfulSync: null,
    nextSync: 0,
  };
  const html = renderToStaticMarkup(
    <IntegrationAppLinks
      items={[
        row,
        { ...row, id: "disabled", name: "Disconnected", enabled: false },
        {
          ...row,
          id: "unsafe",
          name: "Unsafe",
          baseUrl: "javascript:alert(1)",
        },
      ]}
    />,
  );
  expect(html).toContain('href="/integrations/fjordhub"');
  expect(html).not.toContain('target="_blank"');
  expect(html).toContain("FjordHub");
  expect(html).not.toContain("Disconnected");
  expect(html).not.toContain("Unsafe");
});

it("shows licensed artwork or honest interface fallback and installed child apps, excluding catalog entries and unsafe IDs", () => {
  const row: Integration = {
    id: "hub",
    name: "FjordHub",
    baseUrl: "http://192.168.1.40:8888",
    enabled: true,
    tokenConfigured: true,
    allowHttp: true,
    lastSuccessfulSync: null,
    nextSync: 0,
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
        { id: "catalog", name: "Not installed", container_count: 0 },
        { id: "../unsafe", name: "Unsafe child", container_count: 1 },
      ],
    },
  };
  const html = renderToStaticMarkup(<IntegrationAppLinks items={[row]} />);
  expect(html).toContain('data-brand-fallback="fjordhub"');
  expect(html).toContain('href="http://192.168.1.40:8888/#card-fjordflix"');
  expect(html).toContain("FjordFlix");
  expect(html).toContain("Manage in FjordHub (app address unavailable)");
  expect(html).not.toContain("Open FjordFlix");
  expect(html).not.toContain("Not installed");
  expect(html).not.toContain("Unsafe child");
  const legacy = renderToStaticMarkup(
    <IntegrationAppLinks
      items={[
        {
          ...row,
          snapshot: { ...row.snapshot, capabilities: ["app_catalog.read"] },
        },
      ]}
    />,
  );
  expect(legacy).not.toContain("FjordFlix");
  const detected = renderToStaticMarkup(
    <IntegrationAppLinks
      items={[
        { ...row, tokenConfigured: false, snapshot: { status: "detected" } },
      ]}
    />,
  );
  expect(detected).toContain("FjordHub");
  expect(detected).not.toContain("FjordFlix");
});
