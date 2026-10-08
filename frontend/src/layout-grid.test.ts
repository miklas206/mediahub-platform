import { describe, expect, it } from "vitest";
import { gridPosition, placeGridCard } from "./layout-grid";
describe("free card placement", () => {
  it("snaps into empty left, middle and right columns and clamps outside the grid", () => {
    expect(gridPosition(0, 0, 1184, 4)).toEqual({ column: 1, row: 1 });
    expect(gridPosition(400, 72, 1184, 4)).toEqual({ column: 5, row: 4 });
    expect(gridPosition(800, 0, 1184, 4)).toEqual({ column: 9, row: 1 });
    expect(gridPosition(3000, -100, 1184, 4)).toEqual({ column: 9, row: 1 });
  });
  it("pushes collisions down without mutating original cards", () => {
    const cards = [
      { id: "a", column: 1, row: 1, columns: 4, rows: 8 },
      { id: "b", column: 5, row: 1, columns: 4, rows: 10 },
      { id: "c", column: 5, row: 11, columns: 4, rows: 3 },
    ];
    expect(placeGridCard(cards, "a", { column: 5, row: 1 })).toEqual([
      { ...cards[0], column: 5 },
      { ...cards[1], row: 9 },
      { ...cards[2], row: 19 },
    ]);
    expect(cards[0].column).toBe(1);
  });
});
