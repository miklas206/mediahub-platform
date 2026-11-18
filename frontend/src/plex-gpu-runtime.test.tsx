import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PlexGPUPanel } from "./plex-gpu-runtime";
import { PlexGPUHistory } from "./plex-gpu-sessions";
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
  expect(html).toContain('href="http://192.168.1.10:8090/?lang=en"');
  expect(html).toContain("HDR10");
});

it("does not turn unavailable GPU observations into zero usage or an unsafe link", () => {
  const html = renderToStaticMarkup(<PlexGPUPanel report={{ ...report, gpu: undefined, url: "javascript:alert(1)" }} />);
  expect(html).toContain("Not observed");
  expect(html).not.toContain("javascript:");
  expect(html).not.toContain("43 %");
});

describe("Plex GPU activity", () => {
  const report: Runtime = {
    available: true,
    state: "running",
    health: "healthy",
    cached: false,
    agentOnline: true,
    gpu: { name: "NVIDIA", linked: true, activeJobs: 1, encoderPercent: 0 },
  };

  it("shows active encoding even between GPU utilization samples", () => {
    const html = renderToStaticMarkup(<PlexGPUPanel report={report} />);
    expect(html).toContain("Encoding now");
  });

  it("distinguishes idle, stopped and stale observations", () => {
    const idle = { ...report, gpu: { ...report.gpu!, activeJobs: 0 } };
    const stopped = { ...report, state: "stopped" };
    const stale = { ...report, observationHealth: "healthy", cached: true };
    expect(renderToStaticMarkup(<PlexGPUPanel report={idle} />)).toContain(
      "Ready · no active jobs",
    );
    expect(renderToStaticMarkup(<PlexGPUPanel report={stopped} />)).toContain(
      "Stopped",
    );
    const staleHtml = renderToStaticMarkup(<PlexGPUPanel report={stale} />);
    expect(staleHtml).toContain("Last observation");
    expect(staleHtml).not.toContain("Encoding now");
  });
});

it("retains playback details while marking the observation stale", () => {
  const gpu = {
    ...report.gpu!,
    activePlaybacks: 1,
    playbackAvailable: true,
    playbacks: [{ id: "play", media: "Example film", status: "playing", playbackMode: "direct_play", live: true }],
    jobs: [{ id: "job", media: "Previous film", status: "complete", bufferSeconds: 42 }],
  };
  const live = renderToStaticMarkup(<PlexGPUPanel report={{ ...report, gpu }} />);
  expect(live).toContain("Example film");
  expect(live).toContain("Direct Play");
  expect(live).not.toContain("Previous film");
  expect(live).not.toContain("Buffer: 42 sec.");
  const history = renderToStaticMarkup(
    <PlexGPUHistory
      playbacks={[...gpu.playbacks, { ...gpu.jobs[0], live: false }]}
      jobs={gpu.jobs}
      hasObservation
    />,
  );
  expect(history).toContain("Previous film");
  expect(history).toContain("Buffer: 42 sec.");
  expect(history).not.toContain("Example film");
  const stale = renderToStaticMarkup(
    <PlexGPUPanel report={{ ...report, gpu, observationHealth: "healthy" }} />,
  );
  expect(stale).toContain("Example film");
  expect(stale).toContain("Last observation");
  expect(stale).not.toContain("Previous film");
});
