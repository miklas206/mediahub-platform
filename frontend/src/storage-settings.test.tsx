import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { WindowsDriveGuide } from "./storage-settings";
import { SettingsExtensions } from "./phase2";
import { setLanguage } from "./i18n";

afterEach(() => setLanguage("en"));

describe("Storage under Settings", () => {
  it("offers storage without advanced mode and displays its content", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/settings?section=Storage"]}>
        <SettingsExtensions
          general={<p>General</p>}
          maintenance={<p>Health</p>}
          security={<p>Security</p>}
          sections={{ Storage: <p>Storage controller content</p> }}
        />
      </MemoryRouter>,
    );
    expect(html).toContain('aria-selected="true"');
    expect(html).toContain("Storage controller content");
  });
  it("does not offer storage to a user without the administrator section", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <SettingsExtensions
          general={<p>General</p>}
          maintenance={<p>Health</p>}
          security={<p>Security</p>}
        />
      </MemoryRouter>,
    );
    expect(html).not.toContain(">Storage<");
  });
  it("shows the real UNC path and separate SMB account in the Danish Windows guide", () => {
    setLanguage("da");
    const html = renderToStaticMarkup(
      <WindowsDriveGuide
        share={{
          name: "Media",
          unc: "\\\\192.168.1.20\\Media",
          username: "mediahub",
          storageId: "movies",
          readOnly: true,
        }}
      />,
    );
    expect(html).toContain("\\\\192.168.1.20\\Media");
    expect(html).toContain("Tilknyt netværksdrev");
    expect(html).toContain("mediahub");
    expect(html).toContain("adgangskoden til Windows-deling");
    expect(html).not.toContain("ExecutionPolicy");
  });
});
