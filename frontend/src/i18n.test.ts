import { afterEach, describe, expect, it } from "vitest";
import { setLanguage, t } from "./i18n";

afterEach(() => setLanguage("en"));
describe("account language", () => {
  it("translates labels and templates while preserving names and spacing", () => {
    setLanguage("da");
    expect(t("Name")).toBe("Navn");
    expect(t(" Show details ")).toBe(" Vis detaljer ");
    expect(t("Width of {title}", { title: "My RSS" })).toBe("Bredde på My RSS");
    expect(t("User.Show.S01E01.mkv")).toBe("User.Show.S01E01.mkv");
    expect(t("Loading torrents…")).toBe("Indlæser torrents…");
  });
  it("switches back to English without retaining previous translations", () => {
    setLanguage("da");
    expect(t("Customize layout")).toBe("Tilpas layout");
    setLanguage("en");
    expect(t("Customize layout")).toBe("Customize layout");
  });
});
