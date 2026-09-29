import { expect, test } from "@playwright/test";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("fresh wizard resumes and completed installation skips setup", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Welcome to MediaHub" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Get Started" }).click();
  await expect(
    page.getByRole("heading", { name: "System Check", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .getByLabel("Installation token")
    .fill(process.env.MEDIAHUB_QA_TOKEN!);
  await page
    .getByLabel("Username", { exact: true })
    .fill(process.env.MEDIAHUB_QA_USER!);
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.MEDIAHUB_QA_PASSWORD!);
  await page
    .getByLabel("Confirm password")
    .fill(process.env.MEDIAHUB_QA_PASSWORD!);
  await page.getByRole("button", { name: "Create administrator" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Two-factor authentication",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .locator("summary")
    .filter({ hasText: "Advanced: discover an existing installation" })
    .click();
  await page
    .getByRole("button", { name: /Import Existing Installation/ })
    .click();
  await page.getByRole("button", { name: "Scan existing services" }).click();
  await expect(
    page.getByText("Possible plex installation", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Possible qbittorrent installation", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Possible vpn installation", { exact: false }),
  ).toBeVisible();
  await page
    .locator("summary")
    .filter({ hasText: "Possible plex installation" })
    .click();
  await page
    .getByRole("checkbox", { name: "Select for future import planning" })
    .first()
    .check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Storage", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Name", { exact: true }).fill("QA Movies");
  await page
    .getByRole("button", { name: "Browse server", exact: true })
    .click();
  await page
    .getByRole("button", { name: "storage-sandbox", exact: true })
    .click();
  await page.getByLabel("New folder name").fill("movies");
  await page.getByRole("button", { name: "Select new folder" }).click();
  await page
    .getByRole("checkbox", { name: /I confirm creation of exactly/ })
    .check();
  await page.getByRole("button", { name: "Add storage location" }).click();
  await expect(page.getByText("QA Movies", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("QA Movies", { exact: true })).toBeVisible();
  await page.screenshot({ path: "../.qa/setup-resumed.png", fullPage: true });
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .locator("summary")
    .filter({ hasText: "Optional apps and advanced catalog" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Plex", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Foundation Test App")).toHaveCount(0);
  const plex = page
    .locator("section.app-detail")
    .filter({ has: page.getByRole("heading", { name: "Plex", exact: true }) });
  await plex
    .locator("summary")
    .filter({ hasText: "Advanced requirements and configuration" })
    .click();
  await plex.getByRole("button", { name: "Configure", exact: true }).click();
  await plex.getByLabel("Timezone").fill("Europe/Copenhagen");
  await plex.getByRole("button", { name: "Save app configuration" }).click();
  await expect(plex.getByRole("status")).toContainText("Configuration saved");
  await plex.getByRole("button", { name: "Preview plan" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Installation preview — not executable",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Review", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await page
    .getByRole("button", { name: "Apply configuration", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Your MediaHub is ready" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open dashboard" }).click();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Everything, in view." }),
  ).toBeVisible();
  await expect(page.locator(".wizard-shell")).toHaveCount(0);
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page
    .getByLabel("Technical mode: show server, network and diagnostic settings")
    .check();
  await page.getByRole("button", { name: "Show everything" }).click();
  await page.getByRole("button", { name: "All cards" }).click();
  await page.getByRole("button", { name: "Save preferences" }).click();
  await page.getByRole("link", { name: "Dashboard", exact: false }).click();
  await expect(
    page.getByText("Agent connected", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Storage", exact: true }).click();
  await expect(
    page
      .getByLabel("Media location")
      .getByRole("option", { name: "QA Movies", exact: true }),
  ).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: "Upload folder", exact: true }),
  ).toBeEnabled();
  const uploadFixture = await mkdtemp(join(tmpdir(), "mediahub-folder-"));
  try {
    const folder = join(uploadFixture, "Test Film");
    await mkdir(join(folder, "Subtitles"), { recursive: true });
    // Cross the chunk boundary with generated data, not a real movie.
    await writeFile(
      join(folder, "sample.mkv"),
      Buffer.alloc(9 * 1024 * 1024, 65),
    );
    await writeFile(join(folder, "Subtitles", "sample.srt"), "Test subtitle");
    let droppedResponse = false;
    await page.route("**/uploads/*", async (route) => {
      if (route.request().method() !== "PATCH") return route.continue();
      expect(route.request().postDataBuffer()!.length).toBeLessThanOrEqual(
        5 * 1024 * 1024,
      );
      if (!droppedResponse) {
        droppedResponse = true;
        const accepted = await route.fetch();
        expect(accepted.ok()).toBe(true);
        await route.abort();
      } else await route.continue();
    });
    await page
      .getByLabel("Choose folder to upload", { exact: true })
      .setInputFiles(folder);
    await expect(
      page.getByText("2 of 2 files uploaded", { exact: true }),
    ).toBeVisible();
    expect(droppedResponse).toBe(true);
    await page.unroute("**/uploads/*");
    await expect(
      page.getByRole("button", { name: /Test Film.*Folder/ }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Test Film.*Folder/ }).click();
    await expect(
      page.locator(".media-file-list").getByText("sample.mkv", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: /Subtitles.*Folder/ }).click();
    await expect(
      page.locator(".media-file-list").getByText("sample.srt", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Parent folder", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Parent folder", exact: true })
      .click();

    let releaseChunk!: () => void;
    let chunkEntered!: () => void;
    const entered = new Promise<void>((resolve) => {
      chunkEntered = resolve;
    });
    const held = new Promise<void>((resolve) => {
      releaseChunk = resolve;
    });
    await page.route("**/uploads/*", async (route) => {
      if (route.request().method() !== "PATCH") return route.continue();
      chunkEntered();
      await held;
      await route.abort().catch(() => {});
    });
    await page
      .getByLabel("Choose files to upload", { exact: true })
      .setInputFiles([
        {
          name: "cancel-test.mkv",
          mimeType: "application/octet-stream",
          buffer: Buffer.alloc(1024, 66),
        },
        {
          name: "queued-test.mkv",
          mimeType: "application/octet-stream",
          buffer: Buffer.alloc(1024, 67),
        },
      ]);
    await entered;
    await expect(
      page.getByRole("button", {
        name: "Stop upload cancel-test.mkv",
        exact: true,
      }),
    ).toBeVisible();
    await page.screenshot({
      path: "../.qa/upload-stop-desktop.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect
      .poll(() =>
        page
          .locator(".sidebar")
          .evaluate((el) => el.getBoundingClientRect().right),
      )
      .toBeLessThanOrEqual(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: "../.qa/upload-stop-mobile.png",
      fullPage: true,
    });
    await expect(
      page.getByRole("button", { name: "Stop all", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Stop upload queued-test.mkv", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Stop upload cancel-test.mkv", exact: true })
      .click();
    releaseChunk();
    await expect(page.getByText("Stopped", { exact: true })).toHaveCount(2);
    await expect(
      page.getByRole("button", { name: "Upload folder", exact: true }),
    ).toBeEnabled();
    await expect(
      page
        .locator(".media-file-list")
        .getByText("cancel-test.mkv", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page
        .locator(".media-file-list")
        .getByText("queued-test.mkv", { exact: true }),
    ).toHaveCount(0);
    await page.unroute("**/uploads/*");
    await page.setViewportSize({ width: 1440, height: 1000 });
  } finally {
    await rm(uploadFixture, { recursive: true, force: true });
  }
  await page.getByRole("link", { name: "Dashboard", exact: false }).click();
  await expect(
    page.getByText("Agent connected", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Media storage", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: "../.qa/phase2-desktop.png", fullPage: true });
  await page.getByRole("link", { name: "Hosts", exact: true }).click();
  await page.getByRole("button", { name: "Refresh hosts" }).click();
  await expect(
    page.getByRole("heading", { name: "MediaHub Host", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("online", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Generate single-use pairing code" }),
  ).toBeDisabled();
  await page.screenshot({
    path: "../.qa/phase3-hosts-desktop.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "Storage", exact: true }).click();
  await page
    .locator("summary")
    .filter({ hasText: "Technical storage mappings" })
    .click();
  await page.getByLabel("Logical name", { exact: true }).fill("downloads");
  await page.getByLabel("Underlying dataset reference").fill("qa-dataset");
  await page.getByRole("button", { name: "Register dataset" }).click();
  await expect(page.getByRole("status")).toContainText("Metadata saved");
  await page
    .getByRole("combobox", { name: "Logical storage", exact: true })
    .selectOption({ label: "downloads" });
  await page
    .getByRole("combobox", { name: "Host", exact: true })
    .selectOption("local");
  await page.getByLabel("Host-visible path").fill("/planned/downloads");
  await page.getByRole("button", { name: "Save mapping only" }).click();
  await expect(
    page.getByText("/planned/downloads", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Validate access" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.reload();
  await page
    .locator("summary")
    .filter({ hasText: "Technical storage mappings" })
    .click();
  await expect(
    page.getByText("/planned/downloads", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../.qa/phase3-storage-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page
        .locator(".sidebar")
        .evaluate((el) => el.getBoundingClientRect().right),
    )
    .toBeLessThanOrEqual(0);
  await page.screenshot({ path: "../.qa/phase2-mobile.png", fullPage: true });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
