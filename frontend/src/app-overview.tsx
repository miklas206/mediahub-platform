import { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Download,
  Upload,
  ShieldCheck,
} from "lucide-react";
import { api } from "./api";
import { bytes } from "./format";
import { CountryFlag, countryLabel } from "./country-flag";
import { t } from "./i18n";
import "./app-overview.css";

type Torrent = {
  hash: string;
  name: string;
  state: string;
  progress: number;
  dlspeed: number;
  upspeed: number;
};
type Tracker = {
  name: string;
  status: string;
  checkedAt?: number;
  stats?: {
    uploaded?: number;
    downloaded?: number;
    ratio?: number;
    buffer?: number;
    seeding?: number;
    leeching?: number;
    seedbonus?: number;
  };
};
type Profile = {
  id: string;
  name: string;
  healthy: boolean;
  state: string;
  country?: string;
  automatic: boolean;
};
type Snapshot = {
  ready?: boolean;
  enabled?: boolean;
  checkedAt: number;
  torrents?: Torrent[] | null;
  trackers?: Tracker[];
  profiles?: Profile[];
  consumers?: { name: string; profileId: string; ready: boolean }[];
};
type Entry = { status: string; data?: Snapshot };
type Overview = { mediaseed: Entry; mediavpn: Entry };
export function useAppOverview(enabled: boolean) {
  const [data, setData] = useState<Overview>();
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let busy = false;
    async function refresh() {
      if (busy || document.hidden) return;
      busy = true;
      try {
        const result = await api<Overview>(
          "/app-overview",
          "GET",
          undefined,
          controller.signal,
        );
        if (!controller.signal.aborted) setData(result);
      } catch {
        if (!controller.signal.aborted) setData(undefined);
      } finally {
        busy = false;
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [enabled]);
  return enabled ? data : undefined;
}
export function overviewEntry(data: Overview | undefined, packageId: string) {
  return packageId === "org.mediahub.mediaseed"
    ? data?.mediaseed
    : packageId === "org.mediahub.mediavpn"
      ? data?.mediavpn
      : undefined;
}
export function overviewHealth(entry?: Entry) {
  if (
    entry?.status !== "ok" ||
    !entry.data ||
    Date.now() / 1000 - entry.data.checkedAt > 30
  )
    return "unknown";
  if (entry.data.profiles)
    return entry.data.profiles.some((profile) => profile.healthy)
      ? "healthy"
      : "degraded";
  return entry.data.ready ? "healthy" : "degraded";
}
function Country({ country }: { country?: string }) {
  return (
    <span className="overview-country">
      <CountryFlag country={country} size={18} decorative />
      {country ? countryLabel(country) : t("Unknown country")}
    </span>
  );
}
function Fact({ value, label }: { value: string | number; label: string }) {
  return (
    <div>
      <dd>{value}</dd>
      <dt>{t(label)}</dt>
    </div>
  );
}
export function AppOverviewDetails({
  entry,
  vpn,
}: {
  entry?: Entry;
  vpn: boolean;
}) {
  const data = entry?.data;
  if (
    entry?.status !== "ok" ||
    !data ||
    Date.now() / 1000 - data.checkedAt > 30
  )
    return (
      <p className="muted overview-unavailable">
        {t(
          entry?.status === "denied"
            ? "No access to app data"
            : "App data temporarily unavailable",
        )}
      </p>
    );
  if (vpn) {
    const profiles = data.profiles || [];
    return (
      <div className="app-overview-details">
        <dl className="service-facts">
          <Fact
            value={profiles.filter((row) => row.healthy).length}
            label="Connected VPNs"
          />
          <Fact value={profiles.length} label="VPN profiles" />
          <Fact value={data.consumers?.length || 0} label="Apps using VPN" />
        </dl>
        <ul className="overview-profiles">
          {profiles.map((profile) => (
            <li key={profile.id}>
              <div>
                <ShieldCheck size={15} />
                <strong>{profile.name}</strong>
                <span
                  className={profile.healthy ? "overview-connected" : "muted"}
                >
                  {t(
                    profile.healthy
                      ? "Connected"
                      : profile.state === "stopped"
                        ? "Stopped"
                        : "Not verified",
                  )}
                </span>
              </div>
              {profile.healthy && <Country country={profile.country} />}
              <span className="muted">
                {t(
                  profile.automatic
                    ? "Automatic server selection"
                    : "Configuration server",
                )}
              </span>
            </li>
          ))}
        </ul>
        {!profiles.length && (
          <p className="muted">{t("No VPN profiles created")}</p>
        )}
        <div className="overview-consumers">
          <span className="muted">{t("Apps using VPN")}</span>
          {data.consumers?.length ? (
            data.consumers.map((app) => (
              <p key={app.name}>
                <strong>{app.name}</strong>
                <span>
                  {profiles.find((profile) => profile.id === app.profileId)
                    ?.name || "—"}
                </span>
                <span className={app.ready ? "overview-connected" : "muted"}>
                  {t(app.ready ? "Protected" : "Waiting for VPN")}
                </span>
              </p>
            ))
          ) : (
            <p className="muted">{t("No apps connected")}</p>
          )}
        </div>
      </div>
    );
  }
  const rows = data.torrents;
  const active =
    rows?.filter((row) =>
      /^(downloading|metadl|forceddl|stalleddl)$/i.test(row.state),
    ) || [];
  const waiting = rows?.filter((row) => row.state === "queuedDL").length;
  const seeding =
    rows?.filter(
      (row) => row.progress >= 1 && !/stopped|paused|error/i.test(row.state),
    ) || [];
  const download = rows?.reduce((total, row) => total + (row.dlspeed || 0), 0);
  const upload = rows?.reduce((total, row) => total + (row.upspeed || 0), 0);
  return (
    <div className="app-overview-details">
      <dl className="service-facts">
        <Fact value={rows ? active.length : "—"} label="Downloads" />
        <Fact value={rows ? seeding.length : "—"} label="Seeding" />
        <Fact value={rows ? rows.length : "—"} label="Torrents" />
      </dl>
      <div className="overview-speeds">
        <span>
          <ArrowDown size={15} />
          {download == null ? "—" : bytes(download) + "/s"}
        </span>
        <span>
          <ArrowUp size={15} />
          {upload == null ? "—" : bytes(upload) + "/s"}
        </span>
      </div>
      {!!waiting && (
        <p className="muted">
          {t("Queued downloads: {count}", { count: waiting })}
        </p>
      )}
      <ul className="overview-downloads">
        {active.slice(0, 3).map((row) => (
          <li key={row.hash}>
            <div>
              <strong>{row.name}</strong>
              <span>{Math.round(row.progress * 100)} %</span>
            </div>
            <progress max={1} value={row.progress} aria-label={row.name} />
            <span className="muted">
              {bytes(row.dlspeed)}/s ·{" "}
              {t(row.state === "metaDL" ? "Fetching metadata" : "Downloading")}
            </span>
          </li>
        ))}
      </ul>
      {!active.length && (
        <p className="muted">
          {t(rows ? "No active downloads" : "Torrent data unavailable")}
        </p>
      )}
      {active.length > 3 && (
        <p className="muted">
          {t("More downloads: {count}", { count: active.length - 3 })}
        </p>
      )}
      {data.trackers?.map((tracker) => (
        <div className="overview-tracker" key={tracker.name}>
          <div>
            <strong>{tracker.name}</strong>
            <span className="muted">{t("Tracker API")}</span>
          </div>
          {tracker.status === "ok" && tracker.stats ? (
            <>
              <dl className="service-facts">
                <Fact
                  value={tracker.stats.ratio?.toFixed(2) ?? "—"}
                  label="Ratio"
                />
                <Fact value={tracker.stats.seeding ?? "—"} label="Seeding" />
                <Fact
                  value={tracker.stats.seedbonus?.toLocaleString() ?? "—"}
                  label="Bonus"
                />
              </dl>
              <div className="overview-speeds">
                <span>
                  <Upload size={14} />
                  {tracker.stats.uploaded == null
                    ? "—"
                    : bytes(tracker.stats.uploaded)}
                </span>
                <span>
                  <Download size={14} />
                  {tracker.stats.downloaded == null
                    ? "—"
                    : bytes(tracker.stats.downloaded)}
                </span>
              </div>
              <p className="muted">
                {t("Updated")}:{" "}
                {tracker.checkedAt
                  ? new Date(tracker.checkedAt * 1000).toLocaleTimeString()
                  : "—"}
              </p>
            </>
          ) : (
            <p className="muted">
              {t(
                tracker.status === "pending"
                  ? "Waiting for tracker statistics"
                  : "Tracker statistics unavailable",
              )}
            </p>
          )}
        </div>
      ))}
      {rows?.length === 500 && (
        <p className="muted">{t("Showing up to 500 torrents")}</p>
      )}
    </div>
  );
}
