import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setLanguage, translateText } from "./i18n";
import { UpdatesPage } from "./updates";

const state = vi.hoisted(() => ({
  items: [] as Array<Record<string, unknown>>,
  lastError: null as string | null,
}));
vi.mock("./phase2", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useLoad: (path: string) => ({
    data:
      path === "/updates/summary"
        ? {
            checkedAt: 123000,
            count: 0,
            items: state.items,
            intervalHours: 24,
            notifications: [],
            lastError: state.lastError,
          }
        : undefined,
    error: "",
    reload: vi.fn(),
  }),
}));
afterEach(() => {
  setLanguage("en");
  state.items = [];
  state.lastError = null;
});
function render() {
  return renderToStaticMarkup(
    <MemoryRouter>
      <UpdatesPage apps={[]} />
    </MemoryRouter>,
  );
}
describe("deferred Cloudflare update checks", () => {
  it("shows translated cooldown and stale release without claiming success or hiding real errors", () => {
    setLanguage("da");
    state.items = [
      {
        id: "cloudflare",
        name: "Cloudflare Tunnel",
        checkStatus: "deferred",
        stale: true,
        latestVersion: "2026.9.1",
        installedVersion: "2026.8.0",
        updateAvailable: false,
        checkedAt: 123000,
        retryAt: 123456,
        message: "rate limit",
      },
      {
        id: "plex",
        name: "Plex",
        checkStatus: "failed",
        errorCode: "update_source_timeout",
        updateAvailable: false,
        message: "Plex update source timed out",
      },
    ];
    state.lastError = "Could not check: Plex";
    const html = render();
    expect(html).toContain("GitHubs forespørgselsgrænse");
    expect(html).toContain("Tunnelen fungerer uændret");
    expect(html).toContain("Senest verificerede udgivelse: 2026.9.1");
    expect(html).toContain("forældet");
    expect(html).toContain("Plex update source timed out");
    expect(html).toContain("update_source_timeout");
    expect(html).not.toContain("Alle kontrollerede komponenter er opdaterede");
  });
  it("does not label deferred checks as all up to date even without a cache", () => {
    state.items = [
      {
        id: "cloudflare",
        name: "Cloudflare Tunnel",
        checkStatus: "deferred",
        retryAt: 123456,
      },
    ];
    const html = render();
    expect(html).toContain("Some update checks are deferred");
    expect(html).not.toContain("All checked components are up to date");
    expect(html).not.toContain("Last verified release");
  });
  it("translates the backend rate limit message without changing the deadline", () => {
    setLanguage("da");
    const result = translateText(
      "GitHub rate limit reached for cloudflared. Next attempt no earlier than 2026-10-06 00:30 UTC. Tunnel operation is unaffected by this update check.",
    );
    expect(result).toContain("GitHubs forespørgselsgrænse");
    expect(result).toContain("2026-10-06 00:30 UTC");
    expect(result).not.toContain("GitHub rate limit reached");
  });
});
