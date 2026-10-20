import { expect, test } from "@playwright/test";

for (const width of [320, 390, 1440]) {
  test(`Plex library folders stay editable at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    const writes: {
      method: string;
      path: string;
      body: Record<string, unknown>;
    }[] = [];
    const nas = `/media/nas/${"a".repeat(24)}`;
    const oldPath = `${nas}/files/old-folder`;
    let libraries = [
      {
        id: "1",
        name: "Films from Plex",
        type: "movie",
        locations: ["/media/movies/1", oldPath],
        revision: "a".repeat(64),
      },
      {
        id: "2",
        name: "Other Media",
        type: "movie",
        locations: ["/media/other/1"],
        revision: "b".repeat(64),
      },
    ];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.EventSource = class extends EventTarget {
        close() {}
      } as unknown as typeof EventSource;
    });
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.replace(/^\/api(?:\/v1)?/, "");
      let data: unknown = [];
      if (path === "/auth/status") data = { needsSetup: false };
      else if (path === "/auth/me")
        data = {
          id: "admin",
          username: "admin",
          role: "administrator",
          csrf: "test",
          language: "en",
        };
      else if (path === "/settings")
        data = {
          display_name: "MediaHub",
          theme: "dark",
          visible_navigation: ["/", "/settings"],
          dashboard_sections: [],
        };
      else if (path === "/setup/status") data = { setup_required: false };
      else if (path === "/updates/summary")
        data = { count: 0, items: [], notifications: [] };
      else if (path === "/fjordhub/deployment") data = null;
      else if (path === "/app-settings/org.mediahub.plex")
        data = {
          packageId: "org.mediahub.plex",
          name: "Plex",
          externalUrl: "",
          localUrl: "http://192.168.1.20:32400/",
          running: true,
        };
      else if (path === "/storage-control")
        data = {
          available: true,
          nas: [],
          apps: { bindings: [], interrupted: false },
        };
      else if (path === "/plex/library-folders") {
        const folder = url.searchParams.get("path")!;
        data = {
          path: folder,
          folders:
            folder === "/media/movies/1"
              ? [{ name: "New films", path: folder + "/New films" }]
              : [],
          truncated: false,
        };
      } else if (path.startsWith("/plex/libraries")) {
        if (request.method() !== "GET") {
          const body = request.postDataJSON();
          writes.push({ method: request.method(), path, body });
          if (request.method() === "PUT")
            libraries = libraries.map((row) =>
              row.id === "1"
                ? {
                    ...row,
                    locations: body.locations,
                    revision: "c".repeat(64),
                  }
                : row,
            );
          else if (request.method() === "DELETE")
            libraries = libraries.filter((row) => row.id !== "2");
          else if (request.method() === "POST")
            libraries.push({
              id: "3",
              name: body.name,
              locations: body.locations,
              type: "show",
              revision: "d".repeat(64),
            });
          data = { saved: true, mediaPreserved: true };
        } else
          data = {
            available: true,
            roots: [
              { path: "/media/movies/1" },
              { path: "/media/other/1" },
              { path: nas },
            ],
            libraries,
          };
      }
      await route.fulfill({ json: { data } });
    });
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/app-settings/org.mediahub.plex");
    const settings = page.locator(".plex-library-settings");
    await expect(
      settings.getByRole("heading", { name: "Plex libraries and folders" }),
    ).toBeVisible();
    const films = settings.getByRole("article", {
      name: "Films from Plex",
      exact: true,
    });
    await films
      .getByRole("button", { name: "Edit folders", exact: true })
      .click();
    await films
      .getByRole("button", { name: `Remove folder: ${oldPath}`, exact: true })
      .click();
    await films
      .getByLabel("Assigned media storage")
      .selectOption("/media/movies/1");
    await films
      .getByLabel("Open a subfolder")
      .selectOption("/media/movies/1/New films");
    await films
      .getByRole("button", { name: "Use this folder", exact: true })
      .click();
    await films
      .getByRole("button", { name: "Save folders", exact: true })
      .click();
    await expect(
      films.getByRole("button", { name: "Edit folders", exact: true }),
    ).toBeVisible();
    await expect(
      films.getByText("/media/movies/1/New films", { exact: true }),
    ).toBeVisible();
    expect(writes[0]).toMatchObject({
      method: "PUT",
      body: {
        expectedRevision: "a".repeat(64),
        locations: ["/media/movies/1", "/media/movies/1/New films"],
      },
    });
    const other = settings.getByRole("article", {
      name: "Other Media",
      exact: true,
    });
    await other
      .getByRole("button", { name: "Remove library", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toContainText(
      "Media files stay untouched",
    );
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Continue", exact: true })
      .click();
    await expect(other).toHaveCount(0);
    expect(writes[1]).toMatchObject({
      method: "DELETE",
      body: { confirmRemove: true },
    });
    libraries[0].name = "Renamed directly in Plex";
    await settings
      .getByRole("button", { name: "Refresh libraries", exact: true })
      .click();
    await expect(
      settings.getByRole("heading", {
        name: "Renamed directly in Plex",
        exact: true,
      }),
    ).toBeVisible();
    expect(writes).toHaveLength(2);
    await settings
      .getByRole("button", { name: "Create Plex library", exact: true })
      .click();
    const create = settings.locator(".plex-library-create");
    await create.getByLabel("Library name").fill("New series");
    await create.getByLabel("Library type").selectOption("tv");
    await create.getByLabel("Assigned media storage").selectOption(nas);
    await create
      .getByRole("button", { name: "Use this folder", exact: true })
      .click();
    await create
      .getByRole("button", { name: "Create library", exact: true })
      .click();
    await expect(
      settings.getByRole("heading", { name: "New series", exact: true }),
    ).toBeVisible();
    expect(writes[2].body).toMatchObject({
      name: "New series",
      kind: "tv",
      locations: [nas],
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(errors).toEqual([]);
    await page.screenshot({
      path: `test-results/plex-library-folders-${width}.png`,
      fullPage: true,
    });
  });
}
