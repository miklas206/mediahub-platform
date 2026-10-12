import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setLanguage } from "./i18n";
import { UpdatesPage } from "./updates";

const state = vi.hoisted(() => ({
  method: undefined as "deploy-key" | "token" | "public" | undefined,
  tokenConfigured: false,
}));

vi.mock("./phase2", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useLoad: (path: string) => ({
    data:
      path === "/updates/platform"
        ? {
            sourceAccessMethod: state.method,
            repository: "example/private-hub",
            assets: {},
          }
        : path === "/updates/platform/credentials"
          ? { configured: state.tokenConfigured }
          : undefined,
    error: "",
    reload: vi.fn(),
  }),
}));

afterEach(() => {
  setLanguage("en");
  state.method = undefined;
  state.tokenConfigured = false;
});

function render() {
  return renderToStaticMarkup(
    <MemoryRouter>
      <UpdatesPage apps={[]} />
    </MemoryRouter>,
  );
}

describe("platform source access", () => {
  it.each([false, true])(
    "shows host deploy-key access without token controls (saved token: %s)",
    (tokenConfigured) => {
      setLanguage("da");
      state.method = "deploy-key";
      state.tokenConfigured = tokenConfigured;
      const html = render();
      expect(html).toContain(
        "Adgang med en separat læsenøgle er konfigureret på værten.",
      );
      expect(html).not.toContain('type="password"');
      expect(html).not.toContain("inline-secret-form");
      expect(html).not.toContain("Ikke konfigureret");
    },
  );

  it("preserves encrypted token replacement and removal for token access", () => {
    state.method = "token";
    state.tokenConfigured = true;
    const html = render();
    expect(html).toContain("the token is encrypted");
    expect(html).toContain('type="password"');
    expect(html).toContain("Replace private access");
    expect(html).toContain("Remove access");
    expect(html).not.toContain("separate read-only key");
  });

  it.each(["public", undefined] as const)(
    "preserves token setup for public and older responses: %s",
    (method) => {
      state.method = method;
      const html = render();
      expect(html).toContain("public repositories work without a token");
      expect(html).toContain("Save private access");
      expect(html).not.toContain("Remove access");
    },
  );
});
