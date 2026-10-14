import type { Page } from "@playwright/test";

// Inspect rendered text lines, including lines clipped by overflow:hidden cards.
// Scrollable tables and code areas are intentionally allowed to scroll.
export async function textOutsideCards(page: Page) {
  return page.evaluate(() => {
    const findings: string[] = [];
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
    );
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (
        !parent ||
        !node.textContent?.trim() ||
        parent.closest("script,style,svg,option,[aria-hidden=true]")
      )
        continue;
      if (!parent.checkVisibility({ checkVisibilityCSS: true })) continue;
      const card = parent.closest(
        ".panel,.workspace-card,.profile,.gateway-route,.app-settings-panel,.notification-popup,.hub-app-card,dialog[open]",
      );
      if (!card) continue;
      let scrollable = false;
      for (
        let item: Element | null = parent;
        item && item !== card;
        item = item.parentElement
      ) {
        const style = getComputedStyle(item);
        if (
          [style.overflowX, style.overflowY].some(
            (value) => value === "auto" || value === "scroll",
          ) ||
          style.textOverflow === "ellipsis"
        )
          scrollable = true;
      }
      if (scrollable) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const bounds = card.getBoundingClientRect();
      const verticalScroll = ["auto", "scroll"].includes(
        getComputedStyle(card).overflowY,
      );
      for (const line of range.getClientRects()) {
        if (!line.width || !line.height) continue;
        if (
          line.left < bounds.left - 2 ||
          line.right > bounds.right + 2 ||
          (!verticalScroll &&
            (line.top < bounds.top - 2 || line.bottom > bounds.bottom + 2))
        ) {
          findings.push(
            `${card.className || card.id}: ${node.textContent.trim().slice(0, 110)}`,
          );
          break;
        }
      }
    }
    return [...new Set(findings)];
  });
}
