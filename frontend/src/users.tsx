import { useState, type FormEvent } from "react";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { api } from "./api";
import { useData } from "./use-data";
import { NotificationPopup } from "./notification-popup";

type ManagedUser = { id: string; username: string; role: string; createdAt: string };

export function UsersPage({ currentUserId }: { currentUserId: string }) {
  const { data, error, reload } = useData<ManagedUser[]>("/users");
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
      await api(editing.id ? `/users/${editing.id}` : "/users", editing.id ? "PUT" : "POST", { username: editing.username, password });
      setEditing(null);
      setPassword("");
      reload();
    } catch (error) { setFailure((error as Error).message); }
    finally { setBusy(false); }
  }
  async function remove(user: ManagedUser) {
    if (!window.confirm(`Slet brugeren ${user.username}?`)) return;
    setBusy(true);
    setFailure("");
    try { await api(`/users/${user.id}`, "DELETE"); reload(); }
    catch (error) { setFailure((error as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="panel">
    <div className="panel-heading"><h2>Brugere</h2><button disabled={busy} onClick={() => { setEditing({ username: "" }); setPassword(""); }}><Plus size={16} /> {"Tilf\u00f8j bruger"}</button></div>
    {(error || failure) && <NotificationPopup tone="danger">{error || failure}</NotificationPopup>}
    {editing && <form className="settings-form" onSubmit={save}>
      <label>Brugernavn<input required maxLength={80} autoComplete="off" value={editing.username || ""} onChange={event => setEditing({ ...editing, username: event.target.value })} /></label>
      <label>Adgangskode<input type="password" autoComplete="new-password" required={!editing.id} minLength={12} maxLength={256} value={password} onChange={event => setPassword(event.target.value)} /></label>
      <div className="button-row"><button disabled={busy} type="submit">Gem bruger</button><button type="button" onClick={() => setEditing(null)}><X size={16} /> Annuller</button></div>
    </form>}
    <div style={{ overflowX: "auto" }}><table><thead><tr><th>Brugernavn</th><th>Hub-rolle</th><th>Oprettet</th><th>Handlinger</th></tr></thead><tbody>
      {(data || []).map(user => <tr key={user.id}><td>{user.username}{user.id === currentUserId ? " (dig)" : ""}</td><td>{user.role === "administrator" ? "Administrator" : user.role}</td><td>{new Date(user.createdAt).toLocaleDateString("da-DK")}</td><td><div className="button-row"><button title="Rediger bruger" aria-label={`Rediger ${user.username}`} disabled={busy} onClick={() => { setEditing(user); setPassword(""); }}><Pencil size={16} /></button><button title="Slet bruger" aria-label={`Slet ${user.username}`} disabled={busy || user.id === currentUserId} onClick={() => remove(user)}><Trash2 size={16} /></button></div></td></tr>)}
    </tbody></table></div>
  </section>;
}