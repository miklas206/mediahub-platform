import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { FjordFlix } from "./fjordflix";

it("does not invent an error for older FjordHub responses", () => {
  expect(renderToStaticMarkup(<FjordFlix integration="hub" />)).toBe("");
});
it("renders empty successful data and independent stale errors", () => {
  const html = renderToStaticMarkup(
    <FjordFlix
      integration="hub"
      data={{
        ok: true,
        library_count: 0,
        items: [],
        streams: [],
        stale: true,
        error: "FjordFlix data is unavailable.",
      }}
    />,
  );
  expect(html).toContain("No titles in the library.");
  expect(html).toContain("No active streams.");
  expect(html).toContain("stale");
  expect(html).toContain("FjordFlix data is unavailable.");
});
it("preserves API order, Unicode, optional metadata, playback units and local-only posters", () => {
  const html = renderToStaticMarkup(
    <FjordFlix
      integration="hub"
      data={{
        ok: true,
        items: [
          {
            id: "new",
            title: "Æøå newest",
            poster_id: "new",
            overview: "Æøå",
            genres: ["Drama"],
            rating: 8.1,
          },
          { id: "old", title: "Older" },
        ],
        streams: [
          {
            id: "s",
            title: "Æøå stream",
            position: 120,
            duration: 7200,
            height: 1080,
            mbps: 8,
            state: "paused",
            mode: "Direct Play",
            encoder: "Original",
          },
        ],
      }}
    />,
  );
  expect(html.indexOf("Æøå newest")).toBeLessThan(html.indexOf("Older"));
  expect(html).toContain("/api/v1/integrations/hub/fjordflix/posters/new");
  expect(html).toContain("Poster unavailable");
  expect(html).toContain("2:00 / 120:00");
  expect(html).toContain("1080p");
  expect(html).toContain("8 Mbit/s");
  expect(html).toContain("paused · Direct Play");
  expect(html).not.toContain("undefined");
});
it("never creates an external or traversal image request", () => {
  const html = renderToStaticMarkup(
    <FjordFlix
      integration="hub"
      data={{
        ok: true,
        items: [{ title: "Unsafe", poster_id: "../outside?token=x" }],
      }}
    />,
  );
  expect(html).not.toContain("<img");
});
