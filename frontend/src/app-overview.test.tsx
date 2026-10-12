import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { AppOverviewDetails, overviewHealth } from "./app-overview";

it("shows actual torrent progress and cached tracker statistics", () => {
  const entry = {
    status: "ok",
    data: {
      checkedAt: Date.now() / 1000,
      ready: true,
      torrents: [
        {
          hash: "synthetic",
          name: "Test download",
          state: "downloading",
          progress: 0.25,
          dlspeed: 1024,
          upspeed: 0,
        },
      ],
      trackers: [
        {
          name: "Synthetic tracker",
          status: "ok",
          stats: { ratio: 2.5, seeding: 12, uploaded: 1024, downloaded: 512 },
        },
      ],
    },
  };
  const html = renderToStaticMarkup(
    <AppOverviewDetails entry={entry} vpn={false} />,
  );
  expect(html).toContain("Test download");
  expect(html).toContain("25 %");
  expect(html).toContain("Synthetic tracker");
  expect(html).toContain("2.50");
  expect(overviewHealth(entry)).toBe("healthy");
});
it("shows profile countries and actual client binding without implying protection", () => {
  const entry = {
    status: "ok",
    data: {
      checkedAt: Date.now() / 1000,
      profiles: [
        {
          id: "vpn",
          name: "My VPN",
          healthy: true,
          state: "connected",
          country: "DE",
          automatic: true,
        },
      ],
      consumers: [{ name: "MediaSeed", profileId: "vpn", ready: false }],
    },
  };
  const html = renderToStaticMarkup(<AppOverviewDetails entry={entry} vpn />);
  expect(html).toContain("My VPN");
  expect(html).toContain("de.svg");
  expect(html).toContain("MediaSeed");
  expect(html).toContain("Waiting for VPN");
});
it("never displays old health or missing torrent data as a valid zero", () => {
  const entry = {
    status: "ok",
    data: { checkedAt: 1, ready: true, torrents: [] },
  };
  expect(overviewHealth(entry)).toBe("unknown");
  expect(
    renderToStaticMarkup(<AppOverviewDetails entry={entry} vpn={false} />),
  ).not.toContain("No active downloads");
  expect(
    renderToStaticMarkup(
      <AppOverviewDetails
        entry={{
          status: "ok",
          data: { checkedAt: Date.now() / 1000, torrents: null },
        }}
        vpn={false}
      />,
    ),
  ).toContain("Torrent data unavailable");
});
