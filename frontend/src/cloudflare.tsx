import { getLocale, translateText, t } from "./i18n";

import { useCallback, useEffect, useState } from "react";
import { Cloud, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "./api";
import { Panel } from "./phase2";
import "./cloudflare.css";

type Route = {
  url: string;
  hostname: string;
  reachable: boolean;
  statusCode: number | null;
  latencyMs: number;
  message: string;
};
type TunnelStatus = {
  configured: boolean;
  status: "healthy" | "degraded" | "critical" | "not_configured";
  checkedAt: number;
  cached?: boolean;
  metricsReachable: boolean;
  connections: number;
  totalRequests?: number;
  requestErrors?: number;
  version?: string | null;
  tunnelName?: string | null;
  routeCount?: number;
  routes: Route[];
  message: string;
};

export function CloudflareTunnelCard() {
  const [data, setData] = useState<TunnelStatus>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (force = false) => {
    try {
      setData(
        await api<TunnelStatus>(
          `/cloudflare/status${force ? "?refresh=true" : ""}`,
        ),
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(timer);
  }, [load]);
  const state =
    data?.status === "critical" ? "unhealthy" : data?.status || "unknown";
  return (
    <Panel title={t("Cloudflare Tunnel")}>
      <div className="tunnel-heading">
        <div className={`tunnel-icon ${state}`}>
          <Cloud size={23} />
        </div>
        <div>
          <strong>
            {translateText(data?.message) || t("Checking tunnel…")}
          </strong>
          <small>
            {data?.version
              ? t("cloudflared {value0}", { value0: data.version })
              : t("Read-only connection monitor")}
          </small>
        </div>
        <span
          className={`runtime-verdict ${data?.status === "healthy" ? "yes" : data?.status === "critical" ? "no" : "unknown"}`}
        >
          {data?.status === "healthy"
            ? t("Healthy")
            : data?.status === "degraded"
              ? t("Needs attention")
              : data?.status === "critical"
                ? t("Offline")
                : t("Checking")}
        </span>
      </div>
      {error && (
        <div role="alert" className="notice">
          {translateText(error)}
        </div>
      )}
      <div className="tunnel-stats">
        <div>
          <span>{t("Monitored tunnel")}</span>
          <strong>
            {data?.tunnelName ||
              (data?.configured ? t("1 configured") : t("Not configured"))}
          </strong>
        </div>
        <div>
          <span>{t("Connector sessions")}</span>
          <strong>{data?.metricsReachable ? data.connections : "—"}</strong>
        </div>
        <div>
          <span>{t("Published routes")}</span>
          <strong>{data?.routeCount ?? data?.routes.length ?? "—"}</strong>
        </div>
        <div>
          <span>{t("Requests")}</span>
          <strong>
            {data?.totalRequests?.toLocaleString(getLocale()) ?? "—"}
          </strong>
        </div>
      </div>
      {!!data?.routes.length && (
        <div className="tunnel-routes">
          {data.routes.map((route) => (
            <div key={route.url}>
              <ShieldCheck size={18} />
              <div>
                <strong>{route.hostname}</strong>
                <small>
                  {translateText(route.message)} ·{" "}
                  {route.statusCode || t("no response")} · {route.latencyMs}
                  {t(" ms")}
                </small>
              </div>
              <span
                className={`runtime-verdict ${route.reachable ? "yes" : "no"}`}
              >
                {route.reachable ? t("Reachable") : t("Unavailable")}
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="panel-note tunnel-note">
        <span>
          {data?.checkedAt
            ? t("Checked {value0}", {
                value0: new Date(data.checkedAt * 1000).toLocaleTimeString(
                  getLocale(),
                ),
              })
            : t("Waiting for first check")}
        </span>
        <button
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void load(true);
          }}
        >
          <RefreshCw size={15} />
          {t("Refresh")}
        </button>
      </div>
    </Panel>
  );
}
