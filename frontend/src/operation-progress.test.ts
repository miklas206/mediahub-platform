import { describe, expect, it } from "vitest";
import { redactOperationDetail } from "./operation-progress";

describe("operation detail redaction", () => {
  it("redacts credentials before rendering technical details", () => {
    const value = redactOperationDetail(
      "GET /check?token=secret-value&passkey=tracker-key password: hidden github_pat_private_123 Authorization: Bearer private.jwt.value",
    );
    expect(value).not.toContain("secret-value");
    expect(value).not.toContain("tracker-key");
    expect(value).not.toContain("private.jwt.value");
    expect(value).not.toContain("github_pat_private_123");
    expect(value).not.toContain("hidden");
    expect(value).toContain("token=[redacted]");
    expect(value).toContain("passkey=[redacted]");
    expect(value).toContain("Bearer [redacted]");
  });

  it("bounds individual detail lines", () => {
    expect(redactOperationDetail("x".repeat(900))).toHaveLength(500);
  });
});
