import { t } from "./i18n";

export type MaintenanceState = "healthy" | "degraded" | "unknown";

export function canRunMaintenance(
  status: { state: string } | null | undefined,
  error: string,
  checking: boolean,
): boolean {
  return (
    !!status &&
    !error &&
    !checking &&
    !["unavailable", "queued", "running"].includes(status.state)
  );
}

export function installedAppsHealth(
  apps: { health?: { status: string } }[] | null | undefined,
): { state: MaintenanceState; detail: string } {
  if (!apps)
    return { state: "unknown", detail: t("Waiting for the app health check.") };
  if (!apps.length)
    return { state: "unknown", detail: t("No installed apps to check.") };
  const healthy = apps.filter((app) => app.health?.status === "healthy").length;
  const problems = apps.filter((app) =>
    ["degraded", "unhealthy"].includes(app.health?.status || ""),
  ).length;
  const unknown = apps.length - healthy - problems;
  const state = problems ? "degraded" : unknown ? "unknown" : "healthy";
  if (!unknown)
    return {
      state,
      detail: problems
        ? t(
            problems === 1
              ? "{count} app needs attention."
              : "{count} apps need attention.",
            { count: problems },
          )
        : t(
            healthy === 1
              ? "{count} app is healthy."
              : "{count} apps are healthy.",
            { count: healthy },
          ),
    };
  return {
    state,
    detail: t(
      "{healthy} of {total} apps are healthy; {unknown} have unknown health; {problems} need attention.",
      {
        healthy,
        total: apps.length,
        unknown,
        problems,
      },
    ),
  };
}
