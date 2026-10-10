import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { notificationSeason, NotificationSeasonArt, notificationAnimals, nextNotificationAnimal } from "./notification-season";

describe("notification seasons", () => {
  it.each([
    [1, 3, "newyear"], [1, 4, "winter"], [2, 11, "winter"],
    [2, 12, "valentine"], [2, 14, "valentine"], [2, 15, "winter"],
    [3, 1, "spring"], [5, 31, "spring"], [6, 1, "summer"],
    [6, 19, "summer"], [6, 20, "midsummer"], [6, 23, "midsummer"],
    [6, 24, "midsummer"], [6, 25, "summer"], [8, 31, "summer"],
    [9, 1, "autumn"], [10, 19, "autumn"], [10, 20, "halloween"],
    [10, 31, "halloween"], [11, 1, "autumn"], [12, 1, "christmas"],
    [12, 28, "christmas"], [12, 29, "newyear"], [12, 31, "newyear"],
  ])("selects the local variant on %s/%s", (month, day, season) => {
    expect(notificationSeason(new Date(2026, Number(month) - 1, Number(day)))).toBe(season);
  });
  it("renders distinct art for every variant", () => {
    const variants = ["winter", "spring", "summer", "autumn", "halloween", "midsummer", "christmas", "newyear", "valentine"] as const;
    const artwork = variants.map((season) => renderToStaticMarkup(<NotificationSeasonArt season={season} />));
    expect(new Set(artwork).size).toBe(variants.length);
    for (const html of artwork) expect(html).toContain('href="/notification-duck.svg"');
  });
  it("offers ten distinct animals in each of the nine seasons", () => {
    for (const season of ["winter", "spring", "summer", "autumn", "halloween", "midsummer", "christmas", "newyear", "valentine"] as const) {
      const artwork = notificationAnimals.map((animal) => renderToStaticMarkup(<NotificationSeasonArt season={season} animal={animal} />));
      expect(artwork).toHaveLength(10);
      expect(new Set(artwork).size).toBe(10);
    }
  });
  it("never repeats the immediately previous animal", () => {
    for (const previous of notificationAnimals) {
      for (let attempt = 0; attempt < 50; attempt++) {
        const next = nextNotificationAnimal(previous);
        expect(next).not.toBe(previous);
        expect(notificationAnimals).toContain(next);
      }
    }
  });
});