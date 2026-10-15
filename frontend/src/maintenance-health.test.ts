import { afterEach, describe, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import { canRunMaintenance, cleanupSpaceMessage, installedAppsHealth } from "./maintenance-health";

const apps = (...states: string[]) =>
  states.map((status) => ({ health: { status } }));
afterEach(() => setLanguage("en"));

describe("installed app maintenance health", () => {
  it("formats actual cleanup savings without rounding small savings to zero GiB", () => {
    for (const [value, amount] of [[0,"0 B"],[512,"512 B"],[2048,"2.0 KiB"],[3*1024**2,"3.0 MiB"],[2*1024**3,"2.0 GiB"]] as const)
      expect(cleanupSpaceMessage({reclaimedBytes:value})).toContain(amount);
    expect(cleanupSpaceMessage({})).toBe("Freed disk space could not be measured.");
    expect(cleanupSpaceMessage({reclaimedBytes:NaN})).toBe("Freed disk space could not be measured.");
    setLanguage("da");
    expect(cleanupSpaceMessage({reclaimedBytes:1536})).toBe("Målt frigivet diskplads: 1,5 KiB.");
  });
  it("blocks unavailable cleanup and overlapping operations", () => {
    expect(canRunMaintenance(null, "", false)).toBe(false);
    for (const state of ["unavailable", "queued", "running"])
      expect(canRunMaintenance({ state }, "", false)).toBe(false);
    expect(canRunMaintenance({ state: "idle" }, "offline", false)).toBe(false);
    expect(canRunMaintenance({ state: "idle" }, "", true)).toBe(false);
    for (const state of ["idle", "succeeded", "failed"])
      expect(canRunMaintenance({ state }, "", false)).toBe(true);
  });
  it("never labels unknown apps healthy", () => {
    setLanguage("en");
    expect(
      installedAppsHealth(apps("healthy", "healthy", "healthy", "unknown")),
    ).toEqual({
      state: "unknown",
      detail:
        "3 of 4 apps are healthy; 1 have unknown health; 0 need attention.",
    });
    expect(installedAppsHealth([{}])).toEqual({
      state: "unknown",
      detail:
        "0 of 1 apps are healthy; 1 have unknown health; 0 need attention.",
    });
  });
  it("prioritizes known problems and retains unknown counts", () => {
    setLanguage("en");
    expect(
      installedAppsHealth(apps("healthy", "unhealthy", "degraded", "unknown")),
    ).toEqual({
      state: "degraded",
      detail:
        "1 of 4 apps are healthy; 1 have unknown health; 2 need attention.",
    });
    expect(installedAppsHealth(apps("unhealthy")).detail).toBe(
      "1 app needs attention.",
    );
  });
  it("handles all healthy, loading and no installed apps", () => {
    setLanguage("en");
    expect(installedAppsHealth(apps("healthy"))).toEqual({
      state: "healthy",
      detail: "1 app is healthy.",
    });
    expect(installedAppsHealth(apps("healthy", "healthy")).detail).toBe(
      "2 apps are healthy.",
    );
    expect(installedAppsHealth(null).state).toBe("unknown");
    expect(installedAppsHealth([])).toEqual({
      state: "unknown",
      detail: "No installed apps to check.",
    });
  });
  it("localizes the accurate counts in Danish", () => {
    setLanguage("da");
    expect(installedAppsHealth(apps("healthy", "unknown")).detail).toBe(
      "1 af 2 apps er sunde; 1 har ukendt sundhed; 0 kræver opmærksomhed.",
    );
    expect(installedAppsHealth([]).detail).toBe(
      "Ingen installerede apps at kontrollere.",
    );
  });
});
