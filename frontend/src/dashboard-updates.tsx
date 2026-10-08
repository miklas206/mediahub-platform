import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, PackageCheck } from "lucide-react";
import { api } from "./api";
import { t } from "./i18n";
import { ServiceIcon } from "./service-icon";

type Summary = {
  count: number;
  checkedAt: number | null;
  items: {
    id: string;
    name: string;
    installedVersion: string | null;
    latestVersion: string | null;
    updateAvailable: boolean;
    checkStatus?: string;
  }[];
};

export function DashboardUpdates() {
  const [data, setData] = useState<Summary>();
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    async function refresh() {
      if (document.hidden) return;
      try {
        const result = await api<Summary>(
          "/updates/summary",
          "GET",
          undefined,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setData(result);
          setError(false);
        }
      } catch {
        if (!controller.signal.aborted) setError(true);
      }
    }
    void refresh();
    const interval = window.setInterval(() => void refresh(), 30000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, []);
  return (
    <section className="panel dashboard-updates">
      <header className="panel-heading">
        <h2>
          <PackageCheck size={17} />
          {t("Updates")}
        </h2>
        <Link
          className="text-link"
          to="/updates"
          aria-label={t("View all updates")}
        >
          <ArrowUpRight size={15} />
        </Link>
      </header>
      <div className="dashboard-update-list">
        {error ? (
          <p className="muted">{t("Update status unavailable")}</p>
        ) : data?.items?.length ? (
          [...data.items]
            .sort(
              (a, b) => Number(b.updateAvailable) - Number(a.updateAvailable),
            )
            .slice(0, 4)
            .map((item) => (
              <Link
                className="dashboard-update-row"
                key={item.id}
                to="/updates"
              >
                <span className="update-service-mark">
                  <ServiceIcon packageId={item.id} size={25} />
                </span>
                <span>
                  <strong>{item.name}</strong>
                  <small>
                    {item.checkStatus === "deferred"
                      ? t("Update check deferred")
                      : item.checkStatus === "failed"
                        ? t("Check failed")
                        : item.updateAvailable
                          ? t("Available: {version}", {
                              version: item.latestVersion || "—",
                            })
                          : t("Installed: {version}", {
                              version: item.installedVersion || "—",
                            })}
                  </small>
                </span>
                <span
                  className={`update-state-dot ${item.checkStatus === "failed" ? "warning" : item.checkStatus === "deferred" ? "" : "active"}`}
                  title={t(
                    item.checkStatus === "deferred"
                      ? "Update check deferred"
                      : item.checkStatus === "failed"
                        ? "Check failed"
                        : item.updateAvailable
                          ? "Update available"
                          : "Installed",
                  )}
                />
              </Link>
            ))
        ) : (
          <p className="muted">
            {t(data ? "No update information yet" : "Loading updates…")}
          </p>
        )}
      </div>
      <Link className="dashboard-update-footer" to="/updates">
        {data?.count
          ? t("{count} updates available", { count: data.count })
          : t("View update status")}
        <ArrowUpRight size={13} />
      </Link>
    </section>
  );
}
