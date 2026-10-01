import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OperationProgress, type OperationState } from "./operation-progress";

const operation: OperationState = {
  title: "Agent update",
  status: "running",
  progress: 90,
  message: "Verifying update",
  steps: [],
  details: [],
  console: ["Build finished"],
};

describe("Update progress visibility", () => {
  it.each(["success", "error"] as const)(
    "keeps %s status and log without a progress bar",
    (status) => {
      const html = renderToStaticMarkup(
        <OperationProgress activeOnly operation={{ ...operation, status }} />,
      );
      expect(html).not.toContain('role="progressbar"');
      expect(html).not.toContain("90%");
      expect(html).toContain("Build finished");
      expect(html).toContain("Verifying update");
    },
  );
  it("shows progress only for an active connected update", () => {
    expect(
      renderToStaticMarkup(
        <OperationProgress activeOnly operation={operation} />,
      ),
    ).toContain('role="progressbar"');
    expect(
      renderToStaticMarkup(
        <OperationProgress
          activeOnly
          operation={{ ...operation, connectionLost: true }}
        />,
      ),
    ).not.toContain('role="progressbar"');
  });
  it("does not show percentages for update checks", () => {
    expect(
      renderToStaticMarkup(
        <OperationProgress statusOnly operation={operation} />,
      ),
    ).not.toContain('role="progressbar"');
  });
});
