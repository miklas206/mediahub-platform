import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { PlexInstallPage } from "./plex-install";

vi.mock("./phase2", () => ({
  ErrorBox: () => null,
  Panel: ({
    title,
    children,
  }: {
    title: string;
    children: React.ReactNode;
  }) => (
    <section>
      <h2>{title}</h2>
      {children}
    </section>
  ),
  useLoad: (path: string) => ({
    data: path.includes("install-status")
      ? { operation: { state: "idle" } }
      : {
          hostId: "local",
          storage: [
            { id: "movies", kind: "movies", label: "My movies" },
            { id: "tv", kind: "tv", label: "My shows" },
            { id: "appdata", kind: "appdata", label: "App storage" },
            { id: "temp", kind: "temp", label: "Dedicated Temp" },
          ],
        },
    reload: vi.fn(),
    error: undefined,
  }),
}));

describe("Plex installation storage", () => {
  it("offers separate temporary storage without adding it to read-only libraries", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PlexInstallPage />
      </MemoryRouter>,
    );
    expect(html).toContain("Temporary transcoding storage");
    expect(html).toContain("Use app data storage / Temp");
    expect(html).toContain('<option value="temp">Dedicated Temp</option>');
    expect(html.match(/type="checkbox"/g)).toHaveLength(2);
    expect(html).toContain("orphan sessions are cleared before restart");
  });
});
