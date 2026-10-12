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
    <Link to="/"><ArrowLeft size={16} /> Tilbage til apps</Link>
    <h1>{data?.name || "App"}: indstillinger</h1>
    {(error || failure) && <NotificationPopup tone="danger">{error || failure}</NotificationPopup>}
    {notice && <NotificationPopup tone="success">{notice}</NotificationPopup>}
    {data && <section className="panel"><form className="settings-form" onSubmit={event => void save(event)}>
      <label>Ekstern app-adresse<input type="url" maxLength={2048} placeholder="https://app.example.com" value={draft ?? data.externalUrl} onChange={event => setDraft(event.target.value)} disabled={busy} /></label>
      <dl><dt>Lokal adresse</dt><dd style={{ overflowWrap: "anywhere" }}>{data.localUrl || "Ikke registreret"}</dd>{data.ssoManaged && <><dt>Registreret SSO-adresse</dt><dd style={{ overflowWrap: "anywhere" }}>{data.ssoOrigin}</dd></>}</dl>
      <p>{"DNS, HTTPS-certifikat og proxy skal pege p\u00e5 appen, f\u00f8r dom\u00e6net kan bruges. Adressen bliver ikke publiceret automatisk."}</p>
      {data.ssoManaged && <p>{"Den gemte adresse bruges ogs\u00e5 til automatisk hub-login. Nulstil for at bruge appens lokale HTTPS-adresse igen."}</p>}
      <div className="button-row"><button type="submit" disabled={busy}><Save size={16} /> Gem adresse</button><button type="button" disabled={busy || !data.externalUrl} onClick={() => void save(undefined, true)}><RotateCcw size={16} /> Nulstil</button>{data.configurationPath && <Link to={data.configurationPath}><ExternalLink size={16} /> App-konfiguration</Link>}</div>
    </form></section>}
  </div>;
}
