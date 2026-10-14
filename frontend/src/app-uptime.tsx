import { useEffect, useState } from "react";
import { t } from "./i18n";

export function safeAppUrl(value?: string | null, packageId?: string) {
  try {
    const url = new URL(value || "");
    if (
      !["https:", "http:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      return null;
    if (
      packageId === "org.mediahub.plex" &&
      (url.pathname === "/" || url.pathname === "/web")
    )
      url.pathname = "/web/index.html";
    return url.href;
  } catch {
    return null;
  }
}

export function runtimeSeconds(
  startedAt: string | null | undefined,
  running: boolean | null | undefined,
  now: number,
) {
  const start = Date.parse(startedAt || "");
  return running === true && Number.isFinite(start) && start > 0 && start <= now
    ? Math.floor((now - start) / 1000)
    : null;
}

export function AppUptime({
  startedAt,
  running,
  observedAt,
}: {
  startedAt?: string | null;
  running?: boolean | null;
  observedAt?: number;
}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (running !== true) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  const stale = observedAt != null && now / 1000 - observedAt > 30;
  const seconds = stale ? null : runtimeSeconds(startedAt, running, now);
  const pad = (value: number) => String(value).padStart(2, "0");
  const value =
    seconds == null
      ? t(!stale && running === false ? "Stopped" : "Unknown")
      : `${Math.floor(seconds / 86400) > 0 ? t("{days}d", { days: Math.floor(seconds / 86400) }) + " " : ""}${pad(Math.floor(seconds / 3600) % 24)}:${pad(Math.floor(seconds / 60) % 60)}:${pad(seconds % 60)}`;
  return (
    <span className="app-uptime" aria-label={`${t("App uptime")}: ${value}`}>
      {t("App uptime")}: <time title={startedAt || undefined}>{value}</time>
    </span>
  );
}

export function AppAddressLinks({
  localUrl,
  externalUrl,
  packageId,
}: {
  localUrl?: string | null;
  externalUrl?: string | null;
  packageId?: string;
}) {
  const local = safeAppUrl(localUrl, packageId),
    domain = safeAppUrl(externalUrl, packageId);
  return (
    <dl className="app-address-links">
      <div>
        <dt>{t("Local address")}</dt>
        <dd>
          {local ? (
            <a href={local} target="_blank" rel="noopener noreferrer">
              {local}
            </a>
          ) : (
            t("Not registered")
          )}
        </dd>
      </div>
      {domain && (
        <div>
          <dt>{t("Domain address")}</dt>
          <dd>
            <a href={domain} target="_blank" rel="noopener noreferrer">
              {domain}
            </a>
          </dd>
        </div>
      )}
    </dl>
  );
}
