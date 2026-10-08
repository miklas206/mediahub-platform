import { afterEach, describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SeedboxMediaHubLogin } from "./seedbox-mediahub-login";
import { SeedboxWebUI } from "./seedbox-webui";
import { setLanguage } from "./i18n";

afterEach(() => setLanguage("en"));

describe("opt-in MediaHub login copying", () => {
  it.each(["install", "rotate"] as const)(
    "explains one-time %s and incompatible policies",
    (operation) => {
      const markup = renderToStaticMarkup(
        <SeedboxMediaHubLogin operation={operation} />,
      );
      expect(markup).toContain("Use my MediaHub login");
      expect(markup).toContain(
        "Later MediaHub password changes do not update qBittorrent",
      );
      expect(markup).toContain("Shorter MediaHub passwords cannot be copied");
      expect(markup).toContain("using separate credentials is safer");
      expect(markup).not.toContain('name="password"');
      expect(markup).not.toContain("hash");
    },
  );

  it("offers the same opt-in from existing Seedbox Settings", () => {
    const markup = renderToStaticMarkup(<SeedboxWebUI />);
    expect(markup).toContain("Use my MediaHub login");
    expect(markup).toContain("WebUI access is not configured");
    expect(markup).not.toContain("href=");
  });

  it("provides Danish copy and password-change guidance", () => {
    setLanguage("da");
    const markup = renderToStaticMarkup(
      <SeedboxMediaHubLogin operation="rotate" />,
    );
    expect(markup).toContain("Brug mit MediaHub-login");
    expect(markup).toContain("opdaterer ikke qBittorrent");
    expect(markup).toContain("Kortere MediaHub-adgangskoder kan ikke kopieres");
  });
});
