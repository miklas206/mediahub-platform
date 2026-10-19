import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { StopAppButton } from "./app-controls";
const props = {
  appId: "plex",
  name: "Plex",
  packageId: "org.mediahub.plex",
  onChanged: () => {},
};
it("offers start for stopped apps, stop for running apps and disables unknown state", () => {
  const stopped = renderToStaticMarkup(
    <StopAppButton {...props} running={false} />,
  );
  expect(stopped).toContain('aria-label="Start Plex"');
  expect(stopped).toContain("Start app");
  expect(stopped).not.toContain('disabled=""');
  const running = renderToStaticMarkup(
    <StopAppButton {...props} running={true} />,
  );
  expect(running).toContain('aria-label="Stop Plex"');
  expect(running).toContain("Stop app");
  expect(
    renderToStaticMarkup(<StopAppButton {...props} running={null} />),
  ).toContain('disabled=""');
});
