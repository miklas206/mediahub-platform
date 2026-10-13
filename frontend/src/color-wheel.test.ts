import { describe, expect, it } from "vitest";
import { hexToHSV, hsvToHex } from "./color-wheel";
describe("custom color wheel conversion", () => {
 it.each(["#ff0000","#00ff00","#0000ff","#ffffff","#000000","#808080","#123456","#25c9ed"])("round-trips %s without losing color precision", color => {expect(hsvToHex(hexToHSV(color))).toBe(color);});
 it("wraps hue and clamps slider boundaries", () => {expect(hsvToHex({h:480,s:120,v:100})).toBe("#00ff00");expect(hsvToHex({h:-120,s:100,v:50})).toBe("#000080");expect(hsvToHex({h:0,s:0,v:200})).toBe("#ffffff");});
});
