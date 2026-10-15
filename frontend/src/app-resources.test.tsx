import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { ResourceCard, adviceText, type AppResource } from "./app-resources";
const GiB = 1024 ** 3;
const row: AppResource = {
  id: "plex",
  packageId: "org.mediahub.plex",
  name: "Plex",
  available: true,
  editable: true,
  running: true,
  memoryBytes: 3.8 * GiB,
  cpuCores: 1.5,
  limits: { memoryBytes: 4 * GiB, cpuCores: 2 },
  recommendationsEnabled: true,
  recommendations: [
    {
      id: "a".repeat(64),
      metric: "memoryBytes",
      direction: "increase",
      current: 4 * GiB,
      proposed: 6 * GiB,
      peak: 3.8 * GiB,
      windowDays: 1 / 24,
      feasible: true,
    },
  ],
};
const render = (value: AppResource, settings = false) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <ResourceCard row={value} settings={settings} reload={() => {}} />
    </MemoryRouter>,
  );
describe("per-app resource overview", () => {
  it("shows measured consumption, caps and an approval action", () => {
    const html = render(row);
    expect(html).toContain("3.8 GiB");
    expect(html).toContain("4.0 GiB");
    expect(html).toContain("6.0 GiB");
    expect(html).toContain("Approve");
    expect(html).toContain("Edit resources");
    expect(adviceText(row, row.recommendations[0])).toContain(
      "repeatedly peaks",
    );
  });
  it("keeps manual editing available when recommendations are disabled", () => {
    const html = render(
      { ...row, recommendationsEnabled: false, recommendations: [] },
      true,
    );
    expect(html).toContain("Resource recommendations");
    expect(html).not.toContain("checked");
    expect(html).toContain("Edit resources");
    expect(html).not.toContain("Approve");
  });
  it("shows unlimited shared capacity honestly and explains unsupported editing", () => {
    const html = render({
      ...row,
      editable: false,
      reason:
        "Update the paired Agent to enable resource telemetry and limits.",
      limits: { memoryBytes: null, cpuCores: null },
      recommendations: [],
    });
    expect(html).toContain("No limit - shared host capacity");
    expect(html).toContain("Update the paired Agent");
    expect(html).toContain("disabled");
    expect(html).toContain("Open Updates");
  });
});
