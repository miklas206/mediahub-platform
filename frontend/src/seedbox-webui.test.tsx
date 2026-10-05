import { describe, expect, it, afterEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SeedboxWebUI, seedboxWebUIUrl } from "./seedbox-webui";
import { setLanguage } from "./i18n";

afterEach(() => setLanguage("en"));

describe("Seedbox WebUI access", () => {
  it("never guesses a WebUI URL when unconfigured", () => {
    const markup = renderToStaticMarkup(<SeedboxWebUI />);
    expect(markup).toContain("disabled");
    expect(markup).toContain("WebUI access is not configured");
    expect(markup).toContain("MEDIAHUB_OPERATOR_APP_URLS");
    expect(markup).not.toContain("href=");
  });

  it("opens the configured client tunnel without claiming connectivity", () => {
    const markup = renderToStaticMarkup(
      <SeedboxWebUI operatorUrl="http://127.0.0.1:18081/" />,
    );
    expect(markup).toContain('href="http://127.0.0.1:18081/"');
    expect(markup).toContain('target="_blank"');
    expect(markup).toContain('rel="noopener noreferrer"');
    expect(markup).toContain("not connection-tested");
    expect(markup).toContain("authorized SSH tunnel on this device");
    expect(markup).not.toContain("disabled");
  });

  it("allows an explicitly configured existing HTTPS endpoint", () => {
    expect(seedboxWebUIUrl("https://seedbox.example.test/webui/")).toBe(
      "https://seedbox.example.test/webui/",
    );
  });

  it.each([
    "javascript:alert(1)",
    "data:text/html,qbittorrent",
    "//127.0.0.1:18081/",
    "http://user:password@127.0.0.1:18081/",
    "http://127.0.0.1:99999/",
    " http://127.0.0.1:18081/",
    "http://127.0.0.1:18081/\n",
    "http://127.0.0.1:\t18081/",
  ])("rejects unsafe or malformed operator URL %s", (value) => {
    expect(seedboxWebUIUrl(value)).toBeNull();
    const markup = renderToStaticMarkup(<SeedboxWebUI operatorUrl={value} />);
    expect(markup).toContain("disabled");
    expect(markup).not.toContain("href=");
  });

  it("provides Danish setup and protection guidance", () => {
    setLanguage("da");
    const markup = renderToStaticMarkup(<SeedboxWebUI />);
    expect(markup).toContain("Åbn qBittorrent WebUI");
    expect(markup).toContain("WebUI-adgang er ikke konfigureret");
    expect(markup).toContain("CSRF-beskyttelse");
  });
});
