import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { IntegrationAppLinks } from "./integrations";

it("opens configured FjordHub directly without linking disconnected or unsafe entries", () => {
  const row = {
    id: "fjordhub",
    name: "FjordHub",
    baseUrl: "http://192.168.1.40:8888",
    enabled: true,
    tokenConfigured: true,
    allowHttp: true,
    snapshot: { status: "online" },
    lastSuccessfulSync: null,
    nextSync: 0,
  };
  const html = renderToStaticMarkup(
    <IntegrationAppLinks
      items={[
        row,
        { ...row, id: "disabled", name: "Disconnected", enabled: false },
        {
          ...row,
          id: "unsafe",
          name: "Unsafe",
          baseUrl: "javascript:alert(1)",
        },
      ]}
    />,
  );
  expect(html).toContain('href="http://192.168.1.40:8888"');
  expect(html).toContain('target="_blank"');
  expect(html).toContain("FjordHub");
  expect(html).not.toContain("Disconnected");
  expect(html).not.toContain("Unsafe");
});
