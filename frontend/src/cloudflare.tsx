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
  routes: Route[];
  message: string;
};

export function CloudflareTunnelCard() {
  const [data, setData] = useState<TunnelStatus>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (force = false) => {
    try {
      setData(await api<TunnelStatus>(`/cloudflare/status${force ? "?refresh=true" : ""}`));
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
  const state = data?.status === "critical" ? "unhealthy" : data?.status || "unknown";
  return (
    <Panel title="Cloudflare Tunnel">
      <div className="tunnel-heading">
        <div className={`tunnel-icon ${state}`}><Cloud size={23} /></div>
        <div>
          <strong>{data?.message || "Checking tunnel…"}</strong>
          <small>{data?.version ? `cloudflared ${data.version}` : "Read-only connection monitor"}</small>
        </div>
        <span className={`runtime-verdict ${data?.status === "healthy" ? "yes" : data?.status === "critical" ? "no" : "unknown"}`}>
          {data?.status === "healthy" ? "Healthy" : data?.status === "degraded" ? "Needs attention" : data?.status === "critical" ? "Offline" : "Checking"}
        </span>
      </div>
      {error && <div role="alert" className="notice">{error}</div>}
      <div className="tunnel-stats">
        <div><span>Tunnel</span><strong>{data?.connections ? "Connected" : "Disconnected"}</strong></div>
        <div><span>Cloudflare links</span><strong>{data?.connections ?? "—"}</strong></div>
        <div><span>Requests</span><strong>{data?.totalRequests?.toLocaleString() ?? "—"}</strong></div>
        <div><span>Errors</span><strong>{data?.requestErrors?.toLocaleString() ?? "—"}</strong></div>
      </div>
      {!!data?.routes.length && <div className="tunnel-routes">
        {data.routes.map((route) => <div key={route.url}>
          <ShieldCheck size={18}/>
          <div><strong>{route.hostname}</strong><small>{route.message} · {route.statusCode || "no response"} · {route.latencyMs} ms</small></div>
          <span className={`runtime-verdict ${route.reachable ? "yes" : "no"}`}>{route.reachable ? "Reachable" : "Unavailable"}</span>
        </div>)}
      </div>}
      <div className="panel-note tunnel-note">
        <span>{data?.checkedAt ? `Checked ${new Date(data.checkedAt * 1000).toLocaleTimeString()}` : "Waiting for first check"}</span>
        <button disabled={busy} onClick={() => { setBusy(true); void load(true); }}><RefreshCw size={15}/>Refresh</button>
      </div>
    </Panel>
  );
}
