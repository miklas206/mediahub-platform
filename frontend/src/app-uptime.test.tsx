import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { AppAddressLinks, runtimeSeconds, safeAppUrl } from "./app-uptime";

it("counts from runtime start and rejects stopped, missing and future observations", () => {
  const now = Date.parse("2026-10-15T12:00:00Z");
  expect(runtimeSeconds("2026-10-15T10:00:00Z", true, now)).toBe(7200);
  for (const running of [false, null, undefined])
    expect(runtimeSeconds("2026-10-15T10:00:00Z", running, now)).toBeNull();
  for (const date of [null, "invalid", "2026-10-16T10:00:00Z"])
    expect(runtimeSeconds(date, true, now)).toBeNull();
});
it("opens both addresses and the correct Plex web path", () => {
  const html = renderToStaticMarkup(
    <AppAddressLinks
      localUrl="http://192.168.1.10:32400"
      externalUrl="https://plex.example.com"
      packageId="org.mediahub.plex"
    />,
  );
  expect(html).toContain('href="http://192.168.1.10:32400/web/index.html"');
  expect(html).toContain('href="https://plex.example.com/web/index.html"');
  expect(html).toContain('target="_blank"');
  for (const value of [
    "javascript:alert(1)",
    "https://user:password@example.com",
    "not a URL",
  ])
    expect(safeAppUrl(value)).toBeNull();
});

it("normalizes Plex web directory URLs without duplicating its web path", () => {
  expect(
    safeAppUrl("http://192.168.1.20:32400/web/", "org.mediahub.plex"),
  ).toBe("http://192.168.1.20:32400/web/index.html");
});
