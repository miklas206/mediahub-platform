import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

const publicFile = (name: string) =>
  readFileSync(new URL(`../public/${name}`, import.meta.url));

it("declares branded standalone home-screen icons for Android and iOS", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  expect(html).toContain('rel="manifest" href="/manifest.webmanifest"');
  expect(html).toContain(
    'rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png"',
  );
  expect(html).toContain('name="apple-mobile-web-app-title" content="MediaHub"');
  expect(html).toContain('name="apple-mobile-web-app-capable" content="yes"');
  const manifest = JSON.parse(publicFile("manifest.webmanifest").toString());
  expect(manifest).toMatchObject({
    id: "/",
    name: "MediaHub",
    short_name: "MediaHub",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#101719",
    theme_color: "#101719",
  });
  expect(manifest.icons).toEqual(
    [192, 512].map((size) => ({
      src: `/icon-${size}.png`,
      sizes: `${size}x${size}`,
      type: "image/png",
      purpose: "any maskable",
    })),
  );
  for (const [name, size] of [
    ["apple-touch-icon.png", 180],
    ["icon-192.png", 192],
    ["icon-512.png", 512],
  ] as const) {
    const png = publicFile(name);
    expect(png.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
    expect(png.subarray(12, 16).toString()).toBe("IHDR");
    expect(png.readUInt32BE(16)).toBe(size);
    expect(png.readUInt32BE(20)).toBe(size);
  }
});
