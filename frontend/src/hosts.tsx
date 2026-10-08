import { getLocale, translateText, t } from "./i18n";

import { LayoutGroup } from "./page-layout";
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
    <LayoutGroup id="hosts-HostsPage-1" className="stack">
      <Panel title={t("Hosts & agents")}>
        <p className="muted">
          {t(
            "Each host has its own runtime, permissions and storage paths. Status refreshes every 15 seconds.",
          )}
        </p>
        <ErrorBox error={hosts.error || error} />
        <button disabled={busy} onClick={refresh}>
          {t("Refresh hosts")}
        </button>
      </Panel>
      <LayoutGroup id="hosts-HostsPage-2" className="apps-grid">
        {hosts.data?.map((host) => (
          <Panel key={host.id} title={host.name}>
            <div className="button-row">
              <Server />
              <span className="badge">{translateText(host.status)}</span>
              <span>
                {host.local ? t("Default trusted host") : t("Remote host")}
              </span>
            </div>
            <dl className="host-facts">
              <dt>{t("Hostname")}</dt>
              <dd>{host.hostname || t("Not reported")}</dd>
              <dt>{t("Address")}</dt>
              <dd>
                <code>{host.address}</code>
              </dd>
              <dt>{t("System")}</dt>
              <dd>
                {host.os || t("Not reported")} · {host.architecture || "—"}
              </dd>
              <dt>{t("CPU / RAM")}</dt>
              <dd>
                {host.cores ?? "—"}
                {t(" cores ·")}{" "}
                {host.ramBytes ? bytes(host.ramBytes) : t("Not reported")}
              </dd>
              <dt>{t("Docker")}</dt>
              <dd>
                {host.docker?.available
                  ? host.docker.version || t("Available")
                  : t("Unavailable")}
              </dd>
              <dt>{t("Agent")}</dt>
              <dd>{host.version || "—"}</dd>
              <dt>{t("Last seen")}</dt>
              <dd>
                {host.last_seen
                  ? new Date(host.last_seen).toLocaleString(getLocale())
                  : t("Never")}
              </dd>
            </dl>
            <p className="muted">
              {host.capabilities?.join(" · ") || t("No capabilities reported")}
            </p>
            {host.storage?.map((storage) => (
              <div className="storage-row" key={storage.path}>
                <HardDrive />
                <div>
                  <code>{storage.path}</code>
                  <small>
                    {translateText(storage.error) ||
                      t("{value0} free / {value1} total", {
                        value0: bytes(storage.freeBytes ?? 0),
                        value1: bytes(storage.totalBytes ?? 0),
                      })}
                  </small>
                </div>
              </div>
            ))}
            {host.status !== "online" && (
              <p className="notice">
                {t(
                  "Host unavailable. Last known metadata is retained; app operations must not proceed.",
                )}
              </p>
            )}
          </Panel>
        ))}
      </LayoutGroup>
      <Panel title={t("Pair a remote agent")}>
        <p className="muted">
          {t(
            "HTTPS with a trusted certificate is required on Core and the remote Agent. LAN HTTP cannot enroll remote hosts. No permanent token is displayed here.",
          )}
        </p>
        <form className="storage-form" onSubmit={invite}>
          <label>
            {t("Host name")}
            <input
              required
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            {t("Agent HTTPS address")}
            <input
              required
              placeholder={t("https://private-ip:18767")}
              value={address}
              onChange={(e) => setAddress(e.target.value)}
            />
          </label>
          <button disabled={busy || location.protocol !== "https:"}>
            {t("Generate single-use pairing code")}
          </button>
        </form>
        {pairing && (
          <div role="status">
            <p>
              {t("Expires ")}
              {new Date(pairing.expires_at * 1000).toLocaleTimeString(
                getLocale(),
              )}
              {t(". Enter this code only in the intended Agent.")}
            </p>
            <code>{pairing.token}</code>
            <button onClick={() => setPairing(undefined)}>
              {t("Hide code")}
            </button>
          </div>
        )}
      </Panel>
    </LayoutGroup>
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
    <Panel title={t("Shared storage · logical mappings")}>
      <p className="muted">
        {t(
          "One logical dataset, independent paths per host. Registrations do not create shares. Dataset identity is an administrator assertion, not automatic verification.",
        )}
      </p>
      <ErrorBox error={error || storage.error || hosts.error} />
      {message && <p role="status">{translateText(message)}</p>}
      {storage.data?.map((item) => (
        <div key={item.id} className="logical-dataset">
          <h3>
            {item.name}{" "}
            <span className="muted">· {translateText(item.kind)}</span>
          </h3>
          <small>
            {t("Dataset reference: ")}
            {item.dataset_ref}
          </small>
          {!item.mappings.length && (
            <p className="muted">{t("No host mappings yet.")}</p>
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
                  {mapping.access === "ro" ? t("Read only") : t("Read / write")}
                  {t(" · Requires live validation")}
                </small>
              </div>
              <button
                disabled={busy}
                onClick={() =>
                  validate(item.id, mapping.host_id, mapping.access)
                }
              >
                {t("Validate access")}
              </button>
            </div>
          ))}
        </div>
      ))}
      <h3>{t("Register logical storage")}</h3>
      <form className="storage-form" onSubmit={(e) => submit(e, false)}>
        <label>
          {t("Logical name")}
          <input
            name="name"
            placeholder={t("downloads")}
            required
            pattern="[a-zA-Z0-9_-]+"
          />
        </label>
        <label>
          {t("Kind")}
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
          {t("Underlying dataset reference")}
          <input
            name="dataset_ref"
            required
            placeholder={t("storage-owner/dataset")}
          />
        </label>
        <button disabled={busy}>{t("Register dataset")}</button>
      </form>
      <h3>{t("Map an existing directory")}</h3>
      <form className="storage-form" onSubmit={(e) => submit(e, true)}>
        <label>
          {t("Logical storage")}
          <select name="logical_id" required>
            <option value="">{t("Choose dataset")}</option>
            {storage.data?.map((s) => (
              <option value={s.id} key={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("Host")}
          <select name="host_id" required>
            <option value="">{t("Choose host")}</option>
            {hosts.data?.map((h) => (
              <option value={h.id} key={h.id}>
                {h.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("Host-visible path")}
          <input name="path" required placeholder={t("/media/downloads")} />
        </label>
        <label>
          {t("Maximum app access")}
          <select name="access">
            <option value="ro">{t("Read only")}</option>
            <option value="rw">{t("Read / write")}</option>
          </select>
        </label>
        <button disabled={busy}>{t("Save mapping only")}</button>
      </form>
    </Panel>
  );
}
