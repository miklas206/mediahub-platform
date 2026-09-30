import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FjordHubTokenGuide, fjordHubLink } from "./fjordhub-token-guide";

describe("FjordHub token guidance", () => {
  it("links to the app without forwarding URL tokens", () => {
    expect(fjordHubLink("http://192.168.1.20:8888/?token=secret#secret")).toBe(
      "http://192.168.1.20:8888",
    );
    for (const url of [
      "",
      "javascript:alert(1)",
      "https://user:secret@example.com",
    ])
      expect(fjordHubLink(url)).toBeNull();
  });
  it("shows a direct link and the Danish settings labels", () => {
    const html = renderToStaticMarkup(
      <FjordHubTokenGuide baseUrl="http://192.168.1.20:8888" />,
    );
    expect(html).toContain('href="http://192.168.1.20:8888"');
    expect(html).toContain("Indstillinger");
    expect(html).toContain("Adgangstokens");
    expect(html).toContain("Test Connection");
  });
});
