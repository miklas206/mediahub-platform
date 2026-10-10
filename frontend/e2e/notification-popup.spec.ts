import { expect, test } from "@playwright/test";

test("Matrix notifications fit mobile, pause, dismiss and respect reduced motion", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(async () => {
    const load = (path: string) => import(/* @vite-ignore */ path);
    const React = (await load("/node_modules/.vite/deps/react.js")).default;
    const client = (await load("/node_modules/.vite/deps/react-dom_client.js")).default;
    const { NotificationProvider, NotificationPopup } = await load("/src/notification-popup.tsx");
    document.querySelector<HTMLElement>("#root")!.style.display = "none";
    const host = document.createElement("div");
    document.body.append(host);
    client.createRoot(host).render(React.createElement(NotificationProvider, null,
      ...["success", "info", "warning", "danger"].map((tone) =>
        React.createElement(NotificationPopup, { tone, key: tone },
          "Forbindelsen kunne ikke oprettes. Kontrollér serveradressen og prøv igen."))));
  });
  const popups = page.locator(".notification-popups:visible .notification-popup:not(.notification-shard)");
  await expect(popups).toHaveCount(4);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: "test-results/matrix-popups-desktop.png" });
  await page.setViewportSize({ width: 320, height: 844 });
  const error = popups.filter({ has: page.locator(".notification-message") }).first();
  await error.hover();
  await expect(error).toHaveAttribute("data-paused", "true");
  expect(await error.locator(".notification-lifetime").evaluate((element) =>
    getComputedStyle(element).animationPlayState)).toBe("paused");
  const dimensions = await popups.evaluateAll((elements) => elements.map((element) => {
    const box = element.getBoundingClientRect();
    return { width: box.width, left: box.left, right: box.right, viewport: window.innerWidth, scroll: element.scrollWidth, client: element.clientWidth };
  }));
  expect(dimensions.every((box) => box.width >= 250 && box.left >= 0 && box.right <= box.viewport && box.scroll <= box.client), JSON.stringify(dimensions)).toBe(true);
  await page.screenshot({ path: "test-results/matrix-popups-mobile.png" });
  await error.getByRole("button").click();
  await expect(page.locator(".notification-fragment")).toHaveCount(8);
  await expect(popups).toHaveCount(3);
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await popups.first().locator(".notification-code").evaluate((element) =>
    getComputedStyle(element).display)).toBe("none");
  await popups.first().getByRole("button").click();
  await expect(popups).toHaveCount(2);
  await expect(page.locator(".notification-fragment")).toHaveCount(0);
});