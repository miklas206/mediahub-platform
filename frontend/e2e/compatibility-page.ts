import type { Page } from "@playwright/test";
import { join } from "node:path";

export async function prepareCompatibilityPages(page: Page) {
  await page.route("**/__qa-components.js", (route) =>
    route.fulfill({
      path: join(process.env.MEDIAHUB_QA_COMPONENTS!, "components.js"),
      contentType: "application/javascript; charset=utf-8",
    }),
  );
  await page.route("**/__qa-components?*", async (route) => {
    const shell = await route.fetch({
      url: new URL("/", route.request().url()).href,
    });
    const css =
      (await shell.text()).match(/<link[^>]+rel="stylesheet"[^>]*>/g) || [];
    await route.fulfill({
      contentType: "text/html",
      body:
        '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
        css.join("") +
        '</head><body><main id="root"></main><script src="/__qa-components.js"></script></body></html>',
    });
  });
}
