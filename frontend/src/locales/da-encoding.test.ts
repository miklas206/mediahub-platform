import { afterEach, describe, expect, it } from "vitest";
import { setLanguage, t } from "../i18n";
import messages from "./da.json";

afterEach(() => setLanguage("en"));

describe("Danish catalog encoding", () => {
  it("contains no replacement characters, mojibake or question marks inside words", () => {
    for (const [key, translation] of Object.entries(messages)) {
      expect(translation, key).not.toMatch(/[\uFFFD\u00C2\u00C3]/);
      // URL query separators and actual questions already present in the source are valid.
      const embeddedQuestions = /\p{L}\?\p{L}|(?:^|\s)\?\p{L}/gu;
      expect([...translation.matchAll(embeddedQuestions)].length, key).toBeLessThanOrEqual(
        [...key.matchAll(embeddedQuestions)].length,
      );
    }
  });

  it("renders gateway, domain and running-status labels with Danish letters", () => {
    setLanguage("da");
    expect(t("Shared VPN gateway")).toBe("F\u00e6lles VPN-gateway");
    expect(t("Choose a domain")).toBe("V\u00e6lg et dom\u00e6ne");
    expect(t("Container running")).toBe("Containeren k\u00f8rer");
    expect(t("Tunnel created. Install its connector before opening an app domain.")).toBe(
      "Tunnel oprettet. Install\u00e9r dens connector, f\u00f8r du \u00e5bner et app-dom\u00e6ne.",
    );
  });

  it("preserves Danish letters in user values and genuine question marks", () => {
    setLanguage("da");
    const name = "\u00c6gir \u00d8rn \u00c5se \u00e6\u00f8\u00e5";
    expect(t("Delete {name}", { name })).toBe(`Slet ${name}`);
    const question = Object.entries(messages).find(([key, value]) =>
      key.endsWith("?") && value.endsWith("?"),
    );
    expect(question).toBeDefined();
    expect(t(question![0])).toBe(question![1]);
    setLanguage("en");
    expect(t("F\u00e6lles VPN-gateway")).toBe("Shared VPN gateway");
  });
});
