import { afterEach, describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { CountryFlag, countryCode, countryLabel } from "./country-flag";
import { setLanguage } from "./i18n";

afterEach(() => setLanguage("en"));

describe("country flags", () => {
  it("accepts VPN country names, aliases and ISO codes", () => {
    expect(countryCode("dk")).toBe("DK");
    expect(countryCode("Denmark")).toBe("DK");
    expect(countryCode("Danmark")).toBe("DK");
    expect(countryCode(" United_States ")).toBe("US");
    expect(countryCode("UK")).toBe("GB");
    expect(countryCode("Netherlands")).toBe("NL");
  });

  it("localizes country names while keeping local image paths stable", () => {
    setLanguage("da");
    expect(countryLabel("DK")).toBe("Danmark");
    expect(countryLabel("Netherlands")).toBe("Nederlandene");
    const markup = renderToStaticMarkup(<CountryFlag country="Denmark" />);
    expect(markup).toContain('src="/assets/flags/dk.svg"');
    expect(markup).toContain('alt="Danmark"');
    setLanguage("en");
    expect(countryLabel("DK")).toBe("Denmark");
  });

  it("uses a neutral icon for missing or unknown regions", () => {
    expect(countryCode("ZZ")).toBeUndefined();
    expect(countryCode("../../other")).toBeUndefined();
    expect(countryCode(null)).toBeUndefined();
    const markup = renderToStaticMarkup(
      <CountryFlag country="Custom region" />,
    );
    expect(markup).not.toContain("/assets/flags/");
    expect(markup).toContain('aria-label="Custom region"');
    expect(countryLabel("Custom region")).toBe("Custom region");
  });
});
