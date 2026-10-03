import { afterEach, describe, expect, it } from "vitest";
import { countryName, getLocale, setLanguage, t, translateText } from "./i18n";

afterEach(() => setLanguage("en"));
describe("account language", () => {
  it("translates labels and templates while preserving names and spacing", () => {
    setLanguage("da");
    expect(t("Name")).toBe("Navn");
    expect(t(" Show details ")).toBe(" Vis detaljer ");
    expect(t("Width of {title}", { title: "My RSS" })).toBe("Bredde på My RSS");
    expect(t("Width of {title}", { title: "Settings" })).toBe(
      "Bredde på Settings",
    );
    expect(t("User.Show.S01E01.mkv")).toBe("User.Show.S01E01.mkv");
    expect(t("Loading torrents…")).toBe("Indlæser torrents…");
  });
  it("switches back to English without retaining previous translations", () => {
    setLanguage("da");
    expect(t("Customize layout")).toBe("Tilpas layout");
    setLanguage("en");
    expect(t("Customize layout")).toBe("Customize layout");
  });
  it("translates status messages returned by Core and the remote Agent", () => {
    setLanguage("da");
    expect(t("Route reached Cloudflare/origin")).toBe(
      "Ruten nåede Cloudflare/oprindelsesserveren",
    );
    expect(t("Location change blocked; qBittorrent remains stopped")).toBe(
      "Skift af placering blokeret; qBittorrent forbliver stoppet",
    );
    expect(t("Remote app: healthy")).toBe("Fjernapp: Sund");
    expect(
      t("Installer exited with status 3. Inspect the target before retrying."),
    ).toBe(
      "Installationsprogram afsluttede med status 3. Undersøg målet før genforsøg.",
    );
    expect(
      t(
        "Cloudflare monitoring is not configured.\nOpen tunnel settings to configure monitoring.",
      ),
    ).not.toContain("not configured");
  });
  it("preserves placeholder data, numbers and non-text nodes", () => {
    setLanguage("da");
    expect(
      t("Open {value0} · {value1}", {
        value0: "My.Plex.Name",
        value1: "192.168.1.50",
      }),
    ).toBe("Åbn My.Plex.Name · 192.168.1.50");
    expect(translateText(null)).toBeNull();
    expect(translateText(12)).toBe(12);
    expect(t("/media/Downloads/Release.S01E01.mkv")).toBe(
      "/media/Downloads/Release.S01E01.mkv",
    );
  });
  it("translates dynamic maintenance messages without changing versions or hostnames", () => {
    setLanguage("da");
    expect(translateText("Version 0.4.29 is responding.")).toBe(
      "Version 0.4.29 svarer.",
    );
    expect(translateText("mediahub is connected.")).toBe(
      "mediahub er tilsluttet.",
    );
    expect(translateText("5 of 5 locations are available.")).toBe(
      "5 af 5 placeringer er tilg?ngelige.",
    );
    expect(translateText("4 apps are healthy.")).toBe("4 apps er sunde.");
    expect(translateText("1 app needs attention.")).toBe(
      "1 app kr?ver opm?rksomhed.",
    );
    expect(translateText("2 apps need attention.")).toBe(
      "2 apps kr?ver opm?rksomhed.",
    );
    expect(translateText("1 app is healthy.")).toBe("1 app er sund.");
  });
  it("localizes countries without changing their wire value", () => {
    const wireValue = "Denmark";
    setLanguage("da");
    expect(getLocale()).toBe("da-DK");
    expect(countryName(wireValue)).toBe("Danmark");
    expect(countryName("United_States")).toBe("USA");
    expect(countryName("Unknown custom region")).toBe("Unknown custom region");
    setLanguage("en");
    expect(countryName(wireValue)).toBe("Denmark");
    expect(t("Remote app: healthy")).toBe("Remote app: healthy");
  });
});
