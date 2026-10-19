import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  ContainerInstallProgress,
  type ContainerAppStatus,
} from "./container-apps";

const status: ContainerAppStatus = {
  state: "installing",
  installation: {
    app: "jellyfin",
    hostId: "local",
    storageIds: {},
    timezone: "Europe/Copenhagen",
  },
  operation: {
    state: "installing",
    phase: "download",
    progress: 10,
    indeterminate: true,
    message: "Downloading app image",
  },
};

describe("Container app installation progress", () => {
  it("shows a moving download bar without inventing a download percentage", () => {
    const html = renderToStaticMarkup(
      <ContainerInstallProgress app="jellyfin" status={status} />,
    );
    expect(html).toContain('role="progressbar"');
    expect(html).toContain("Install Jellyfin");
    expect(html).toContain("Working...");
    expect(html).not.toContain("aria-valuenow=");
    expect(html).toContain("Creating app container");
  });
  it("shows server-observed phase progress after reloading", () => {
    const html = renderToStaticMarkup(
      <ContainerInstallProgress
        app="jellyfin"
        status={{
          ...status,
          operation: {
            ...status.operation!,
            phase: "container",
            progress: 80,
            indeterminate: false,
          },
        }}
      />,
    );
    expect(html).toContain('aria-valuenow="80"');
    expect(html).toContain("80%");
  });
  it("retains the failure phase and hides confirmed completed installations", () => {
    const failure = renderToStaticMarkup(
      <ContainerInstallProgress
        app="jellyfin"
        status={{
          ...status,
          operation: {
            ...status.operation!,
            state: "failed",
            indeterminate: false,
          },
        }}
      />,
    );
    expect(failure).toContain('class="operation-progress error"');
    expect(failure).not.toContain("100%");
    const done = renderToStaticMarkup(
      <ContainerInstallProgress
        app="jellyfin"
        status={{
          ...status,
          state: "running",
          operation: {
            state: "installed",
            phase: "complete",
            progress: 100,
            message: "Container started",
          },
        }}
      />,
    );
    expect(done).toBe("");
  });
  it("also displays progress from an older Agent which only reports installing", () => {
    expect(
      renderToStaticMarkup(
        <ContainerInstallProgress
          app="jellyfin"
          status={{ ...status, operation: { state: "installing" } }}
        />,
      ),
    ).toContain('role="progressbar"');
    expect(
      renderToStaticMarkup(<ContainerInstallProgress app="jellyfin" />),
    ).toBe("");
  });
});
