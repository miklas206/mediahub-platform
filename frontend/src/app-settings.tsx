import { AppControlPanel, type AppControls } from "./app-controls";
import { t } from "./i18n";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ExternalLink, Save, RotateCcw } from "lucide-react";
import { api } from "./api";
import { useData } from "./use-data";
import { NotificationPopup } from "./notification-popup";
import { AppAddressLinks, AppUptime } from "./app-uptime";
import type { Health } from "./contracts";

type AppSettings = {
  installationId?: string | null;
  controls?: AppControls;
  name: string;
  packageId: string;
  externalUrl: string;
  localUrl: string | null;
  ssoOrigin: string | null;
  ssoManaged: boolean;
  configurationPath: string | null;
  version?: string | null;
  state?: string;
  runtimeState?: string;
  health?: Health;
  running?: boolean | null;
  startedAt?: string | null;
  observedAt?: number;
  containers?: { name: string; state: string; health?: string | null }[];
};

export function AppSettingsPage({
  packageId: explicitPackage,
  embedded = false,
}: { packageId?: string; embedded?: boolean } = {}) {
  const params = useParams();
  const packageId = explicitPackage || params.packageId || "";
  const { data, error, reload } = useData<AppSettings>(
    `/app-settings/${encodeURIComponent(packageId)}`,
  );
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  useEffect(() => {
    const refresh = () => {
      if (!document.hidden) reload();
    };
    const timer = window.setInterval(refresh, 10000);
    window.addEventListener("focus", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
    };
  }, [reload]);
  async function save(event?: FormEvent, reset = false) {
    event?.preventDefault();
    setBusy(true);
    setFailure("");
    setNotice("");
    try {
      await api(`/app-settings/${encodeURIComponent(packageId)}`, "PUT", {
        externalUrl: reset ? "" : (draft ?? data?.externalUrl ?? ""),
      });
      setDraft(null);
      reload();
      setNotice(
        reset ? "App-adressen er nulstillet." : "App-adressen er gemt.",
      );
      window.dispatchEvent(new Event("apps-changed"));
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="stack app-status-page">
      {!embedded && (
        <>
          <Link className="text-link" to="/">
            <ArrowLeft size={16} /> {t("Back to MediaHub")}
          </Link>
          <h1>
            {data?.name || "App"} · {t("App status")}
          </h1>
        </>
      )}
      {(error || failure) && (
        <NotificationPopup tone="danger">{error || failure}</NotificationPopup>
      )}
      {notice && <NotificationPopup tone="success">{notice}</NotificationPopup>}
      {data && (
        <>
          {!embedded && (
            <section className="panel">
              <div className="panel-heading">
                <h2>{t("App status")}</h2>
                <button onClick={reload}>{t("Refresh status")}</button>
              </div>
              <div className="phase-content">
                <dl className="app-status-facts">
                  <div>
                    <dt>{t("State")}</dt>
                    <dd>
                      {t(
                        data.runtimeState === "restarting"
                          ? "Restarting"
                          : data.running === true
                            ? "Running"
                            : data.running === false
                              ? "Stopped"
                              : "Unknown",
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Health")}</dt>
                    <dd>{t(data.health?.summary || "Status unavailable")}</dd>
                  </div>
                  <div>
                    <dt>{t("Version")}</dt>
                    <dd>
                      {data.version && data.version !== "connected"
                        ? data.version
                        : t("Unknown")}
                    </dd>
                  </div>
                </dl>
                <AppUptime
                  startedAt={data.startedAt}
                  running={error ? null : data.running}
                  observedAt={data.observedAt}
                />
                {data.health?.checks?.length ? (
                  <ul>
                    {data.health.checks.map((check) => (
                      <li key={check.name}>
                        {check.name}: {t(check.message || check.status)}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {data.containers?.length ? (
                  <dl className="app-status-facts">
                    {data.containers.map((container) => (
                      <div key={container.name}>
                        <dt>{container.name}</dt>
                        <dd>
                          {t(container.state)}
                          {container.health ? ` · ${t(container.health)}` : ""}
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </div>
            </section>
          )}
          <section className="panel">
            <div className="panel-heading">
              <h2>{t("App addresses")}</h2>
            </div>
            <div className="phase-content">
              <AppAddressLinks
                packageId={packageId}
                localUrl={data.localUrl}
                externalUrl={data.externalUrl}
              />
              {embedded && (
                <AppUptime
                  startedAt={data.startedAt}
                  running={error ? null : data.running}
                  observedAt={data.observedAt}
                />
              )}
              {!embedded && (
                <form
                  className="settings-form app-address-form"
                  onSubmit={(event) => void save(event)}
                >
                  <label>
                    {t("External app address")}
                    <input
                      type="url"
                      maxLength={2048}
                      placeholder="https://app.example.com"
                      value={draft ?? data.externalUrl}
                      onChange={(event) => setDraft(event.target.value)}
                      disabled={busy}
                    />
                  </label>
                  <p>
                    {t(
                      "DNS, the HTTPS certificate and proxy must point to the app before the domain can be used. The address is not published automatically.",
                    )}
                  </p>
                  {data.ssoManaged && (
                    <p>
                      {t(
                        "The saved address is also used for automatic hub login. Reset to use the app's local HTTPS address again.",
                      )}
                    </p>
                  )}
                  <div className="button-row">
                    <button type="submit" disabled={busy}>
                      <Save size={16} /> {t(" Save address")}
                    </button>
                    <button
                      type="button"
                      disabled={busy || !data.externalUrl}
                      onClick={() => void save(undefined, true)}
                    >
                      <RotateCcw size={16} /> {t("Reset")}
                    </button>
                    {data.configurationPath && (
                      <Link className="button-link" to={data.configurationPath}>
                        <ExternalLink size={16} /> {t(" App configuration")}
                      </Link>
                    )}
                  </div>
                </form>
              )}
            </div>
          </section>
          {!embedded && (
            <AppControlPanel
              appId={data.installationId}
              name={data.name}
              packageId={packageId}
              controls={data.controls}
              openUrl={data.externalUrl || data.localUrl}
              onChanged={reload}
            />
          )}
        </>
      )}
    </div>
  );
}
