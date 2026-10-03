import { readFileSync, readdirSync } from "node:fs";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import danish from "./locales/da.json";

const dictionary: Record<string, string> = danish;

describe("interface translation coverage", () => {
  it("has Danish translations for every literal translation key, including conditional labels", () => {
    const missing: string[] = [];
    for (const filename of readdirSync(new URL(".", import.meta.url))) {
      if (!filename.endsWith(".tsx") || filename.includes(".test.")) continue;
      const source = ts.createSourceFile(
        filename,
        readFileSync(new URL(filename, import.meta.url), "utf8"),
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX,
      );
      function checkKey(node: ts.Node) {
        if (
          ts.isStringLiteral(node) &&
          /[a-zA-Z]/.test(node.text) &&
          !dictionary[node.text.trim()]
        )
          missing.push(`${filename}: ${node.text}`);
        if (ts.isConditionalExpression(node)) {
          checkKey(node.whenTrue);
          checkKey(node.whenFalse);
        }
      }
      function visit(node: ts.Node) {
        if (
          ts.isCallExpression(node) &&
          node.expression.getText(source) === "t" &&
          node.arguments[0]
        )
          checkKey(node.arguments[0]);
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
    expect(missing).toEqual([]);
  });
  it("retains every placeholder so translated actions and diagnostics keep their data", () => {
    const placeholders = (value: string) =>
      [...new Set(value.match(/\{\w+\}/g) || [])].sort();
    const broken = Object.entries(dictionary).filter(
      ([source, translated]) =>
        JSON.stringify(placeholders(source)) !==
        JSON.stringify(placeholders(translated)),
    );
    expect(broken).toEqual([]);
  });
});
