import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, afterEach } from "vitest";
import { AppStorageForm, type AppStorageInventory } from "./app-storage";
import { setLanguage } from "./i18n";

afterEach(() => setLanguage("en"));
const data: AppStorageInventory = {
  available: true,
  nas: [
    { id: "a".repeat(24), label: "My NAS", ready: true, readOnly: false },
    { id: "b".repeat(24), label: "Archive", ready: true, readOnly: true },
    { id: "c".repeat(24), label: "Offline NAS", ready: false, readOnly: false },
  ],
  apps: { bindings: [], interrupted: false },
};
function form(app: "mediaseed" | "plex", value = data) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <AppStorageForm
        app={app}
        data={value}
        busy={false}
        change={async () => {}}
      />
    </MemoryRouter>,
  );
}

describe("NAS storage for apps", () => {
  it("explains Plex read-only access and shows the actual library path", () => {
    const html = form("plex", {
      ...data,
      apps: {
        bindings: [
          {
            app: "plex",
            storageId: data.nas[0].id,
            path: "/media/nas/" + data.nas[0].id + "/files",
            readOnly: true,
          },
        ],
        interrupted: false,
      },
    });
    expect(html).toContain("/media/nas/" + data.nas[0].id + "/files");
    expect(html).toContain("Plex gets read-only access");
    expect(html).toContain("Remove from app");
    expect(html).toContain("Stop Plex in MediaHub");
  });
  it("does not offer disconnected or read-only NAS storage for torrent writes", () => {
    const html = form("mediaseed");
    expect(html).toContain(`value="${data.nas[1].id}" disabled=""`);
    expect(html).toContain(`value="${data.nas[2].id}" disabled=""`);
    expect(html).toContain("never the system disk");
    expect(html).toContain("Stop MediaSeed and MediaVPN");
  });
  it("allows read-only archive selection for Plex", () => {
    const html = form("plex");
    expect(html).toContain(
      `<option value="${data.nas[1].id}">Archive</option>`,
    );
  });
  it("describes the workflow in Danish", () => {
    setLanguage("da");
    const html = form("plex");
    expect(html).toContain("Vælg NAS-lager");
    expect(html).toContain("Plex får læseadgang");
    expect(html).toContain("Tilknyt lager");
  });
});
