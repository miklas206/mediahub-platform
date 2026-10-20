import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { PlexGPUPanel } from "./plex-gpu-runtime";
import type { Runtime } from "./runtime";

const report: Runtime = { health: "healthy", available: true, cached: false,
  agentOnline: true, url: "http://192.168.1.10:8090/", gpu: {
    name: "Test NVIDIA", linked: true, hdrToneMapping: true, encoderPercent: 43,
    memoryUsedMiB: 512, memoryTotalMiB: 8192, temperature: 40, activeJobs: 2,
  } };

it("shows observed encoder usage and the separate dashboard", () => {
  const html = renderToStaticMarkup(<PlexGPUPanel report={report} />);
  expect(html).toContain("43 %");
  expect(html).toContain("Test NVIDIA");
  expect(html).toContain('href="http://192.168.1.10:8090/"');
  expect(html).toContain("HDR10");
});

it("does not turn unavailable GPU observations into zero usage or an unsafe link", () => {
  const html = renderToStaticMarkup(<PlexGPUPanel report={{ ...report, gpu: undefined, url: "javascript:alert(1)" }} />);
  expect(html).toContain("Not observed");
  expect(html).not.toContain("javascript:");
  expect(html).not.toContain("43 %");
});
