import { afterEach, describe, expect, it, vi } from "vitest";
import {
  appearanceTokens,
  applySavedAppearance,
  beginAppearanceSave,
  clearAppearancePreview,
  contrastRatio,
  defaultAppearance,
  getAppearanceSession,
  finishAppearanceSave,
  previewAppearance,
  readAppearance,
  setAppearance,
  setAccountAppearance,
} from "./appearance";

afterEach(() => {
  setAccountAppearance(null);
  vi.unstubAllGlobals();
});

describe("personal appearance", () => {
  it("serializes saves across navigation and isolates pending requests per login", () => {
    const first = beginAppearanceSave();
    expect(first).toBe(getAppearanceSession());
    expect(beginAppearanceSave()).toBeNull();
    finishAppearanceSave(first!);
    const second = beginAppearanceSave();
    expect(second).toBe(first);
    setAccountAppearance(null);
    const current = beginAppearanceSave();
    expect(current).not.toBe(second);
    finishAppearanceSave(second!);
    expect(beginAppearanceSave()).toBeNull();
    finishAppearanceSave(current!);
    expect(beginAppearanceSave()).toBe(current);
  });
  it("accepts complete palettes and rejects invalid stored values", () => {
    expect(readAppearance({ ...defaultAppearance, accent: "#AABBCC" })).toEqual(
      { ...defaultAppearance, accent: "#aabbcc" },
    );
    for (const accent of ["red", "#123", "#12345g", "url(example)", 123, null])
      expect(readAppearance({ ...defaultAppearance, accent })).toBeNull();
    for (const depth of [-1, 101, 1.5, true, "50", null, undefined])
      expect(readAppearance({ ...defaultAppearance, depth })).toBeNull();
    expect(readAppearance({ accent: "#123456" })).toBeNull();
    expect(readAppearance(null)).toBeNull();
  });

  it.each([true, false])(
    "keeps text readable for extreme colors and shades (dark=%s)",
    (dark) => {
      const colors = [
        "#000000",
        "#ffffff",
        "#ff0000",
        "#00ff00",
        "#0000ff",
        "#ffff00",
      ];
      for (const background of colors)
        for (const accent of colors)
          for (const depth of [0, 50, 100]) {
            const tokens = appearanceTokens(
              { accent, secondary: accent, background, depth },
              dark,
            );
            for (const surface of [
              "--bg",
              "--surface",
              "--raised",
              "--sidebar",
              "--accent-bg",
            ])
              for (const foreground of [
                "--text",
                "--muted",
                "--accent",
                "--indigo",
                "--blue",
              ])
                expect(
                  contrastRatio(tokens[surface], tokens[foreground]),
                  `${background}/${accent}/${depth}: ${foreground} on ${surface}`,
                ).toBeGreaterThanOrEqual(4.5);
            expect(
              contrastRatio(tokens["--accent"], tokens["--accent-contrast"]),
            ).toBeGreaterThanOrEqual(4.5);
            expect(tokens).not.toHaveProperty("--healthy");
            expect(tokens).not.toHaveProperty("--warning");
            expect(tokens).not.toHaveProperty("--danger");
          }
    },
  );

  it("discards previews and removes overrides when resetting or leaving an account", () => {
    const properties = new Map<string, string>();
    properties.set("--unrelated", "preserved");
    vi.stubGlobal("document", {
      documentElement: {
        dataset: { theme: "dark" },
        style: {
          setProperty: (key: string, value: string) =>
            properties.set(key, value),
          removeProperty: (key: string) => properties.delete(key),
        },
      },
    });
    const saved = { ...defaultAppearance, accent: "#e2a1ff" };
    setAppearance(saved);
    const savedAccent = properties.get("--accent");
    previewAppearance({ ...saved, accent: "#ffe500" });
    expect(properties.get("--accent")).not.toBe(savedAccent);
    clearAppearancePreview();
    expect(properties.get("--accent")).toBe(savedAccent);
    previewAppearance(null);
    expect(properties.has("--accent")).toBe(false);
    clearAppearancePreview();
    expect(properties.get("--accent")).toBe(savedAccent);
    setAppearance(null);
    expect([...properties.entries()]).toEqual([["--unrelated", "preserved"]]);
    const previousLogin = getAppearanceSession();
    setAccountAppearance(null);
    expect(applySavedAppearance(saved, previousLogin)).toBe(false);
    expect(properties.has("--accent")).toBe(false);
    expect(applySavedAppearance(saved, getAppearanceSession())).toBe(true);
    expect(properties.get("--accent")).toBe(savedAccent);
  });
});
