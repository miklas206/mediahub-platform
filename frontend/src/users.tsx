import { t, getLocale, setLanguage } from "./i18n";
import { useState, type FormEvent } from "react";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { api } from "./api";
import { useData } from "./use-data";
import { NotificationPopup } from "./notification-popup";

type ManagedUser = { id: string; username: string; role: string; language: "en" | "da"; createdAt: string; appRoles: Record<string, string> };

export function UsersPage({ currentUserId }: { currentUserId: string }) {
  const { data, error, reload } = useData<ManagedUser[]>("/users");
  const apps = useData<{ id: string; packageId: string; name: string; ssoSupported?: boolean }[]>("/apps?include_health=false");
  const [editing, setEditing] = useState<Partial<ManagedUser> | null>(null);
  const [password, setPassword] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    setBusy(true);
    setFailure("");
    try {
      await api(editing.id ? `/users/${editing.id}` : "/users", editing.id ? "PUT" : "POST", { username: editing.username, password, role: editing.role || "user", appRoles: editing.appRoles || {}, language: editing.language || "en" });
      if (editing.id === currentUserId) setLanguage(editing.language || "en");
      setEditing(null);
      setPassword("");
      reload();
    } catch (error) { setFailure((error as Error).message); }
    finally { setBusy(false); }
  }
  async function remove(user: ManagedUser) {
    if (!window.confirm(t("Delete user {name}?", {name: user.username}))) return;
    setBusy(true);
    setFailure("");
    try { await api(`/users/${user.id}`, "DELETE"); reload(); }
    catch (error) { setFailure((error as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="panel">
    <div className="panel-heading"><h2>{t("Users")}</h2><button disabled={busy} onClick={() => { setEditing({ username: "", role: "user", appRoles: {} }); setPassword(""); }}><Plus size={16} /> {t("Add user")}</button></div>
    {(error || failure) && <NotificationPopup tone="danger">{error || failure}</NotificationPopup>}
    {editing && <form className="settings-form" onSubmit={save}>
      <label>{t("Language")}<select value={editing.language || "en"} onChange={event => setEditing({...editing, language: event.target.value as "en" | "da"})}><option value="da">{t("Dansk")}</option><option value="en">{t("English")}</option></select></label>
      <label>{t("Username")}<input required maxLength={80} autoComplete="off" value={editing.username || ""} onChange={event => setEditing({ ...editing, username: event.target.value })} /></label>
      <label>{t("Password")}<input type="password" autoComplete="new-password" required={!editing.id} minLength={12} maxLength={256} value={password} onChange={event => setPassword(event.target.value)} /></label>
      <label>{t("Hub role")}<select value={editing.role || "user"} onChange={event => setEditing({ ...editing, role: event.target.value })}><option value="user">{t("User")}</option><option value="administrator">{t("Administrator")}</option></select></label>
      {(apps.data || []).filter(app => app.ssoSupported).map(app => <label key={app.id}>{app.name}<select aria-label={t("Access to {name}", {name: app.name})} value={editing.appRoles?.[app.packageId] || (editing.role === "administrator" ? "administrator" : "denied")} onChange={event => setEditing({ ...editing, appRoles: { ...editing.appRoles, [app.packageId]: event.target.value } })}><option value="denied">{t("No access")}</option><option value="viewer">{ t("Read access") }</option><option value="user">{t("User")}</option><option value="administrator">{t("App administrator")}</option></select></label>)}
      {apps.error && <NotificationPopup tone="danger">{apps.error}</NotificationPopup>}
      <div className="button-row"><button disabled={busy} type="submit">{t("Save user")}</button><button type="button" onClick={() => setEditing(null)}><X size={16} /> {t(" Cancel")}</button></div>
    </form>}
    <div style={{ overflowX: "auto" }}><table><thead><tr><th>{t("Username")}</th><th>{t("Hub role")}</th><th>{t("Created")}</th><th>{t("Actions")}</th></tr></thead><tbody>
      {(data || []).map(user => <tr key={user.id}><td>{user.username}{user.id === currentUserId ? t(" (you)") : ""}</td><td>{t(user.role === "administrator" ? "Administrator" : "User")}</td><td>{new Date(user.createdAt).toLocaleDateString(getLocale())}</td><td><div className="button-row"><button title={t("Edit user")} aria-label={t("Edit {name}", {name: user.username})} disabled={busy} onClick={() => { setEditing(user); setPassword(""); }}><Pencil size={16} /></button><button title={t("Delete user")} aria-label={t("Delete {name}", {name: user.username})} disabled={busy || user.id === currentUserId} onClick={() => remove(user)}><Trash2 size={16} /></button></div></td></tr>)}
    </tbody></table></div>
  </section>;
}
