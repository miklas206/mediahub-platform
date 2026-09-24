import { useEffect, useState, type FormEvent } from "react";
import { Server, HardDrive } from "lucide-react";
import { api } from "./api";
import { bytes } from "./format";
import { ErrorBox, Panel, useLoad } from "./phase2";

export type HostInfo = {
  id: string;
  name: string;
  address: string;
  local: boolean;
  status: string;
  last_seen: string | null;
  hostname?: string;
  os?: string;
  architecture?: string;
  version?: string;
  cores?: number;
  ramBytes?: number;
  capabilities?: string[];
  docker?: { available: boolean; version?: string; composeVersion?: string };
  storage?: {
    path: string;
    freeBytes?: number;
    totalBytes?: number;
    error?: string;
  }[];
};
export type LogicalStorage = {
  id: string;
  name: string;
  kind: string;
  dataset_ref: string;
  mappings: { host_id: string; path: string; access: string }[];
};

export function HostsPage() {
  const hosts = useLoad<HostInfo[]>("/hosts");
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [pairing, setPairing] = useState<{
    token: string;
    expires_at: number;
  }>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const timer = setInterval(hosts.reload, 15000);
    return () => clearInterval(timer);
  }, [hosts.reload]);
  useEffect(() => {
    if (!pairing) return;
    const timer = setTimeout(
      () => setPairing(undefined),
      Math.max(0, pairing.expires_at * 1000 - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [pairing]);
  async function refresh() {
    setBusy(true);
    try {
      await api("/hosts/refresh", "POST");
      hosts.reload();
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function invite(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setPairing(undefined);
    try {
      setPairing(await api("/hosts/pairing", "POST", { name, address }));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="stack">
      <Panel title="Hosts & agents">
        <p className="muted">
          Each host has its own runtime, permissions and storage paths. Status
          refreshes every 15 seconds.
        </p>
        <ErrorBox error={hosts.error || error} />
        <button disabled={busy} onClick={refresh}>
          Refresh hosts
        </button>
      </Panel>
      <div className="apps-grid">
        {hosts.data?.map((host) => (
          <Panel key={host.id} title={host.name}>
            <div className="button-row">
              <Server />
              <span className="badge">{host.status}</span>
              <span>{host.local ? "Default trusted host" : "Remote host"}</span>
            </div>
            <dl className="host-facts">
              <dt>Hostname</dt>
              <dd>{host.hostname || "Not reported"}</dd>
              <dt>Address</dt>
              <dd>
                <code>{host.address}</code>
              </dd>
              <dt>System</dt>
              <dd>
                {host.os || "Not reported"} · {host.architecture || "—"}
              </dd>
              <dt>CPU / RAM</dt>
              <dd>
                {host.cores ?? "—"} cores ·{" "}
                {host.ramBytes ? bytes(host.ramBytes) : "Not reported"}
              </dd>
              <dt>Docker</dt>
              <dd>
                {host.docker?.available
                  ? host.docker.version || "Available"
                  : "Unavailable"}
              </dd>
              <dt>Agent</dt>
              <dd>{host.version || "—"}</dd>
              <dt>Last seen</dt>
              <dd>
                {host.last_seen
                  ? new Date(host.last_seen).toLocaleString()
                  : "Never"}
              </dd>
            </dl>
            <p className="muted">
              {host.capabilities?.join(" · ") || "No capabilities reported"}
            </p>
            {host.storage?.map((storage) => (
              <div className="storage-row" key={storage.path}>
                <HardDrive />
                <div>
                  <code>{storage.path}</code>
                  <small>
                    {storage.error ||
                      `${bytes(storage.freeBytes ?? 0)} free / ${bytes(storage.totalBytes ?? 0)} total`}
                  </small>
                </div>
              </div>
            ))}
            {host.status !== "online" && (
              <p className="notice">
                Host unavailable. Last known metadata is retained; app
                operations must not proceed.
              </p>
            )}
          </Panel>
        ))}
      </div>
      <Panel title="Pair a remote agent">
        <p className="muted">
          HTTPS with a trusted certificate is required on Core and the remote
          Agent. LAN HTTP cannot enroll remote hosts. No permanent token is
          displayed here.
        </p>
        <form className="storage-form" onSubmit={invite}>
          <label>
            Host name
            <input
              required
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Agent HTTPS address
            <input
              required
              placeholder="https://private-ip:18767"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
          </label>
          <button disabled={busy || location.protocol !== "https:"}>
            Generate single-use pairing code
          </button>
        </form>
        {pairing && (
          <div role="status">
            <p>
              Expires {new Date(pairing.expires_at * 1000).toLocaleTimeString()}
              . Enter this code only in the intended Agent.
            </p>
            <code>{pairing.token}</code>
            <button onClick={() => setPairing(undefined)}>Hide code</button>
          </div>
        )}
      </Panel>
    </div>
  );
}

export function LogicalStoragePanel() {
  const storage = useLoad<LogicalStorage[]>("/storage/logical");
  const hosts = useLoad<HostInfo[]>("/hosts");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>, mapping: boolean) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try {
      if (mapping)
        await api(`/storage/logical/${values.logical_id}/mapping`, "PUT", {
          host_id: values.host_id,
          path: values.path,
          access: values.access,
        });
      else await api("/storage/logical", "POST", values);
      storage.reload();
      setError("");
      setMessage(
        "Metadata saved. No mount, copy, move or permission change was performed.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function validate(id: string, host_id: string, access: string) {
    setBusy(true);
    setMessage("");
    try {
      await api(`/storage/logical/${id}/validate`, "POST", { host_id, access });
      setError("");
      setMessage(
        "Agent can access this directory. This does not prove both hosts use the same underlying dataset, nor test app-user permissions.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel title="Shared storage · logical mappings">
      <p className="muted">
        One logical dataset, independent paths per host. Registrations do not
        create shares. Dataset identity is an administrator assertion, not
        automatic verification.
      </p>
      <ErrorBox error={error || storage.error || hosts.error} />
      {message && <p role="status">{message}</p>}
      {storage.data?.map((item) => (
        <div key={item.id} className="logical-dataset">
          <h3>
            {item.name} <span className="muted">· {item.kind}</span>
          </h3>
          <small>Dataset reference: {item.dataset_ref}</small>
          {!item.mappings.length && (
            <p className="muted">No host mappings yet.</p>
          )}
          {item.mappings.map((mapping) => (
            <div className="storage-row" key={mapping.host_id}>
              <HardDrive />
              <div>
                <strong>
                  {hosts.data?.find((h) => h.id === mapping.host_id)?.name ||
                    mapping.host_id}
                </strong>
                <code>{mapping.path}</code>
                <small>
                  {mapping.access === "ro" ? "Read only" : "Read / write"} ·
                  Requires live validation
                </small>
              </div>
              <button
                disabled={busy}
                onClick={() =>
                  validate(item.id, mapping.host_id, mapping.access)
                }
              >
                Validate access
              </button>
            </div>
          ))}
        </div>
      ))}
      <h3>Register logical storage</h3>
      <form className="storage-form" onSubmit={(e) => submit(e, false)}>
        <label>
          Logical name
          <input
            name="name"
            placeholder="downloads"
            required
            pattern="[a-zA-Z0-9_-]+"
          />
        </label>
        <label>
          Kind
          <select name="kind">
            {[
              "downloads",
              "movies",
              "tv",
              "backups",
              "appdata",
              "temp",
              "custom",
            ].map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </label>
        <label>
          Underlying dataset reference
          <input
            name="dataset_ref"
            required
            placeholder="storage-owner/dataset"
          />
        </label>
        <button disabled={busy}>Register dataset</button>
      </form>
      <h3>Map an existing directory</h3>
      <form className="storage-form" onSubmit={(e) => submit(e, true)}>
        <label>
          Logical storage
          <select name="logical_id" required>
            <option value="">Choose dataset</option>
            {storage.data?.map((s) => (
              <option value={s.id} key={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Host
          <select name="host_id" required>
            <option value="">Choose host</option>
            {hosts.data?.map((h) => (
              <option value={h.id} key={h.id}>
                {h.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Host-visible path
          <input name="path" required placeholder="/media/downloads" />
        </label>
        <label>
          Maximum app access
          <select name="access">
            <option value="ro">Read only</option>
            <option value="rw">Read / write</option>
          </select>
        </label>
        <button disabled={busy}>Save mapping only</button>
      </form>
    </Panel>
  );
}
