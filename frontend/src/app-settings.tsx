import { t } from "./i18n";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ExternalLink, Save, RotateCcw } from "lucide-react";
import { api } from "./api";
import { useData } from "./use-data";
import { NotificationPopup } from "./notification-popup";

type AppSettings = { name: string; externalUrl: string; localUrl: string | null; ssoOrigin: string | null; ssoManaged: boolean; configurationPath: string | null };

export function AppSettingsPage() {
  const { packageId = "" } = useParams();
  const { data, error, reload } = useData<AppSettings>(`/app-settings/${encodeURIComponent(packageId)}`);
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  async function save(event?: FormEvent, reset = false) {
    event?.preventDefault();
    setBusy(true); setFailure(""); setNotice("");
    try {
      await api(`/app-settings/${encodeURIComponent(packageId)}`, "PUT", { externalUrl: reset ? "" : draft ?? data?.externalUrl ?? "" });
      setDraft(null); reload();
      setNotice(reset ? "App-adressen er nulstillet." : "App-adressen er gemt.");
      window.dispatchEvent(new Event("apps-changed"));
    } catch (error) { setFailure((error as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="stack">
    <Link to="/"><ArrowLeft size={16} /> {t(" Back to apps")}</Link>
    <h1>{data?.name || "App"}{t(": settings")}</h1>
    {(error || failure) && <NotificationPopup tone="danger">{error || failure}</NotificationPopup>}
    {notice && <NotificationPopup tone="success">{notice}</NotificationPopup>}
    {data && <section className="panel"><form className="settings-form" onSubmit={event => void save(event)}>
      <label>{t("External app address")}<input type="url" maxLength={2048} placeholder="https://app.example.com" value={draft ?? data.externalUrl} onChange={event => setDraft(event.target.value)} disabled={busy} /></label>
      <dl><dt>{t("Local address")}</dt><dd style={{ overflowWrap: "anywhere" }}>{data.localUrl || t("Not registered")}</dd>{data.ssoManaged && <><dt>{t("Registered SSO address")}</dt><dd style={{ overflowWrap: "anywhere" }}>{data.ssoOrigin}</dd></>}</dl>
      <p>{t("DNS, the HTTPS certificate and proxy must point to the app before the domain can be used. The address is not published automatically.")}</p>
      {data.ssoManaged && <p>{t("The saved address is also used for automatic hub login. Reset to use the app's local HTTPS address again.")}</p>}
      <div className="button-row"><button type="submit" disabled={busy}><Save size={16} /> {t(" Save address")}</button><button type="button" disabled={busy || !data.externalUrl} onClick={() => void save(undefined, true)}><RotateCcw size={16} /> {t("Reset")}</button>{data.configurationPath && <Link to={data.configurationPath}><ExternalLink size={16} /> {t(" App configuration")}</Link>}</div>
    </form></section>}
  </div>;
}
