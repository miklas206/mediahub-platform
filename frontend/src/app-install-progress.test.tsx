import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { PlexInstallProgress } from "./plex-install-progress";
import {
  FjordHubInstallProgress,
  SeedboxInstallProgress,
} from "./legacy-install-progress";
import { setLanguage } from "./i18n";

afterEach(() => setLanguage("en"));

describe("App installation progress", () => {
  it("shows Plex download activity without inventing a byte percentage", () => {
    const html = renderToStaticMarkup(
      <PlexInstallProgress
        job={{
          action: "install",
          state: "running",
          phase: "download",
          progress: 10,
          indeterminate: true,
        }}
      />,
    );
    expect(html).toContain('role="progressbar"');
    expect(html).not.toContain("aria-valuenow=");
    expect(html).toContain("Working...");
  });
  it("retains Plex's observed phase during reconnection and failure", () => {
    const html = renderToStaticMarkup(
      <PlexInstallProgress
        connectionLost
        job={{
          action: "install",
          state: "running",
          phase: "container",
          progress: 80,
        }}
      />,
    );
    expect(html).toContain("Last known progress: 80%");
    const failure = renderToStaticMarkup(
      <PlexInstallProgress
        job={{
          action: "install",
          state: "failed",
          phase: "download",
          progress: 10,
          message: "Image download failed",
        }}
      />,
    );
    expect(failure).toContain('class="operation-progress error"');
    expect(failure).not.toContain("100%");
    expect(failure).toContain("Image download failed");
  });
  it("shows confirmed Plex completion and ignores unrelated operations", () => {
    expect(
      renderToStaticMarkup(
        <PlexInstallProgress job={{ action: "install", state: "succeeded" }} />,
      ),
    ).toContain('aria-valuenow="100"');
    expect(
      renderToStaticMarkup(
        <PlexInstallProgress
          job={{ state: "running", message: "Updating Plex" }}
        />,
      ),
    ).toBe("");
  });
  it("translates Plex installation progress into Danish", () => {
    setLanguage("da");
    expect(
      renderToStaticMarkup(
        <PlexInstallProgress
          job={{
            action: "install",
            state: "running",
            phase: "download",
            indeterminate: true,
          }}
        />,
      ),
    ).toContain("Henter app-image");
  });
  it("keeps FjordHub indeterminate until the deployment confirms completion", () => {
    const html = renderToStaticMarkup(
      <FjordHubInstallProgress state="running" message="Installing FjordHub" />,
    );
    expect(html).toContain('role="progressbar"');
    expect(html).not.toContain("aria-valuenow=");
    expect(
      renderToStaticMarkup(
        <FjordHubInstallProgress state="succeeded" message="Completed" />,
      ),
    ).toContain('aria-valuenow="100"');
    expect(
      renderToStaticMarkup(
        <FjordHubInstallProgress state="interrupted" message="Interrupted" />,
      ),
    ).toContain('class="operation-progress error"');
  });
  it("derives Seedbox progress from completed safety steps, preserving interrupted states", () => {
    const transaction = {
      state: "Installing",
      steps: [
        { id: "preflight", state: "Succeeded" },
        { id: "verify_api", state: "Running" },
      ],
    };
    expect(
      renderToStaticMarkup(
        <SeedboxInstallProgress transaction={transaction} />,
      ),
    ).toContain('aria-valuenow="50"');
    expect(
      renderToStaticMarkup(
        <SeedboxInstallProgress
          transaction={{
            ...transaction,
            state: "ManualIntervention",
            failedStep: "verify_api",
          }}
        />,
      ),
    ).toContain('class="operation-progress error"');
    expect(
      renderToStaticMarkup(
        <SeedboxInstallProgress
          transaction={{ ...transaction, state: "Healthy" }}
        />,
      ),
    ).toContain('aria-valuenow="100"');
  });
});
