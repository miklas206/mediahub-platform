import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ErrorBox, Panel } from "./phase2";
import { bytes, uptime } from "./format";
import { SeedboxRSS } from "./seedbox-rss-feeds";
import {
  TorrentRetention,
  defaultRetention,
  type RetentionRule,
} from "./torrent-retention";

type Torrent = {
  hash: string;
  name: string;
  progress: number;
  state: string;
  dlspeed: number;
  upspeed: number;
  ratio: number;
  eta: number;
  size: number;
  actionsAllowed: boolean;
  num_seeds?: number;
  num_leechs?: number;
  category?: string;
  seeding_time?: number;
  retention?: RetentionRule | null;
  retentionMessage?: string;
};
type DownloadLocation = { id: string; label: string; storageLabel?: string };
type Listing = {
  items: Torrent[];
  storageId: string;
  downloadLocations?: DownloadLocation[];
  limit: number;
  retentionSupported?: boolean;
};
type Locations = {
  provider: string;
  available: boolean;
  countries: string[];
  servers: { id: string; country: string; name: string }[];
  current: {
    country: string;
    server: string;
    countryEvidence: string;
    externalIp?: string;
  } | null;
  operation: { state: string; step: string | null };
  automaticDescription: string;
  automation?: {
    enabled?: boolean;
    intervalHours?: number;
    message?: string;
    samples?: Record<string, { downloadMbps: number; uploadMbps: number }>;
  };
};

export function SeedboxDaily({
  externalIp,
  forwarding,
}: {
  externalIp?: string | null;
  forwarding?: string;
}) {
  const [intervalHours, setIntervalHours] = useState<number | null>(null);
  const [list, setList] = useState<Listing | null>(null),
    [location, setLocation] = useState<Locations | null>(null);
  const [retention, setRetention] = useState<RetentionRule>(defaultRetention);
  const [cleanupEdit, setCleanupEdit] = useState<{
    hash: string;
    name: string;
    rule: RetentionRule;
  } | null>(null);
  const [error, setError] = useState(""),
    [listError, setListError] = useState(""),
    [locationError, setLocationError] = useState("");
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const [downloadLocationsSupported, setDownloadLocationsSupported] = useState<
    boolean | null
  >(null);
  const [country, setCountry] = useState(""),
    [server, setServer] = useState("automatic");
  const [mode, setMode] = useState("magnet"),
    [magnet, setMagnet] = useState(""),
    [file, setFile] = useState<File | null>(null),
    [start, setStart] = useState(false),
    [downloadLocation, setDownloadLocation] = useState("root");
  const reload = useCallback(() => {
    void api<Listing>("/seedbox/torrents")
      .then((v) => {
        setDownloadLocationsSupported(Array.isArray(v.downloadLocations));
        const downloadLocations = v.downloadLocations?.length
          ? v.downloadLocations.filter((item) => item.label === "Top folder")
          : [{ id: "root", label: "Top folder" }];
        setList({ ...v, downloadLocations });
        setDownloadLocation((current) =>
          downloadLocations.some((item) => item.id === current)
            ? current
            : downloadLocations[0]?.id || "root",
        );
        setListError("");
      })
      .catch(() =>
        setListError(
          "Torrent list unavailable during runtime changes or failed safety checks.",
        ),
      );
    void api<Locations>("/seedbox/locations")
      .then((v) => {
        setLocation(v);
        setLocationError("");
      })
      .catch(() => setLocationError("VPN location catalog unavailable."));
  }, []);
  useEffect(() => {
    reload();
    const timer = setInterval(reload, 5000);
    return () => clearInterval(timer);
  }, [reload]);
  const changing = location?.operation.state === "running";
  async function action(hash: string, action: string) {
    if (
      action === "remove" &&
      !window.confirm("Remove this torrent job? Downloaded files will be kept.")
    )
      return;
    if (
      action === "recheck" &&
      !window.confirm(
        "Check the downloaded pieces on disk? This can take a while for large files. Files will not be deleted.",
      )
    )
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/seedbox/torrents/action", "POST", { hash, action });
      setNotice(
        action === "remove"
          ? "Torrent job removed. Files were kept."
          : "Torrent action accepted.",
      );
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function add(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!list) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const body: Record<string, unknown> = {
        storageId: list.storageId,
        startImmediately: start,
        retention,
      };
      if (downloadLocation !== "root")
        body.downloadLocationId = downloadLocation;
      if (mode === "magnet") body.magnet = magnet;
      else {
        if (
          !file ||
          !file.name.toLowerCase().endsWith(".torrent") ||
          file.size > 2 * 1024 * 1024
        )
          throw Error("Choose a .torrent file up to 2 MiB.");
        const data = new Uint8Array(await file.arrayBuffer());
        let binary = "";
        for (let i = 0; i < data.length; i += 8192)
          binary += String.fromCharCode(...data.subarray(i, i + 8192));
        body.torrentBase64 = btoa(binary);
      }
      const result = await api<{ state: string }>(
        "/seedbox/torrents/add",
        "POST",
        body,
      );
      setMagnet("");
      setFile(null);
      setRetention(defaultRetention);
      setNotice(
        result.state === "already_present"
          ? "Torrent is already present; no settings changed."
          : "Torrent added.",
      );
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function change() {
    const selected = country || location?.current?.country || "";
    if (
      !selected ||
      !window.confirm(
        `Switch VPN to ${selected}? qBittorrent will stop until all checks pass.`,
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      await api("/seedbox/locations", "POST", {
        country: selected,
        server,
        intervalHours:
          intervalHours ?? location?.automation?.intervalHours ?? 6,
      });
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const selected = country || location?.current?.country || "";
  return (
    <div className="stack seedbox-daily">
      <ErrorBox error={error} />
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
      <div className="runtime-panels">
        <Panel title="VPN Location">
          <ErrorBox error={locationError} />
          <div className="runtime-row">
            <span>Current</span>
            <strong>{location?.current?.country || "Not identified"}</strong>
          </div>
          <div className="runtime-row">
            <span>External IP</span>
            <strong>{externalIp || "Not verified"}</strong>
          </div>
          <div className="runtime-row">
            <span>Port forwarding</span>
            <strong>{forwarding || "Not verified"}</strong>
          </div>
          <label>
            Country
            <select
              value={selected}
              disabled={busy || changing}
              onChange={(e) => {
                setCountry(e.target.value);
                setServer("automatic");
              }}
            >
              <option value="">Select country</option>
              {location?.countries.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label>
            Server
            <select
              value={server}
              disabled={busy || changing}
              onChange={(e) => setServer(e.target.value)}
            >
              <option value="automatic">Automatic · P2P server</option>
              {location?.servers
                .filter((s) => s.country === selected)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} · {s.id}
                  </option>
                ))}
            </select>
          </label>
          {server === "automatic" && (
            <label>
              Compare server speeds
              <select
                value={
                  intervalHours ?? location?.automation?.intervalHours ?? 6
                }
                disabled={busy || changing}
                onChange={(e) => setIntervalHours(Number(e.target.value))}
              >
                <option value={6}>
                  Every 6 hours ? switch only for a clear improvement
                </option>
                <option value={24}>Once a day ? fewer interruptions</option>
                <option value={0}>Only when I select automatic manually</option>
              </select>
            </label>
          )}
          {location?.automation?.message && (
            <p role="status">{location.automation.message}</p>
          )}
          {location?.automation?.samples &&
            Object.entries(location.automation.samples).map(([id, sample]) => (
              <p className="muted" key={id}>
                {id}: {sample.downloadMbps} Mbps down / {sample.uploadMbps} Mbps
                up
              </p>
            ))}
          <button
            className="primary"
            disabled={busy || changing || !location?.available || !selected}
            onClick={() => void change()}
          >
            Change VPN location
          </button>
          {changing && (
            <progress aria-label="VPN location switch in progress" />
          )}
          <p role="status">{location?.operation.step || "Ready"}</p>
          <p className="muted">
            {location?.current?.countryEvidence}.{" "}
            {location?.automaticDescription}
          </p>
        </Panel>
        <Panel title="Add Torrent">
          <form onSubmit={(e) => void add(e)}>
            <label>
              Input type
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="magnet">Magnet Link</option>
                <option value="file">Torrent File</option>
              </select>
            </label>
            {mode === "magnet" ? (
              <label>
                Magnet link
                <textarea
                  value={magnet}
                  onChange={(e) => setMagnet(e.target.value)}
                  maxLength={16384}
                  required
                  placeholder="magnet:?xt=urn:btih:…"
                  autoComplete="off"
                />
              </label>
            ) : (
              <label>
                Torrent file
                <input
                  type="file"
                  accept=".torrent"
                  required
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
              </label>
            )}
            <label>
              Download location
              <select
                value={downloadLocation}
                disabled={
                  busy || changing || !(list?.downloadLocations?.length ?? 0)
                }
                onChange={(event) => setDownloadLocation(event.target.value)}
              >
                {list?.downloadLocations?.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.storageLabel || "Downloads"}
                  </option>
                ))}
              </select>
            </label>
            {downloadLocationsSupported === false && (
              <p className="muted">
                This Seedbox Agent still supports the Downloads top folder only.
                Install the matching Agent update and configure writable logical
                storage to enable Film, TV and Other choices.
              </p>
            )}
            <label>
              <input
                type="checkbox"
                checked={start}
                onChange={(e) => setStart(e.target.checked)}
              />{" "}
              Start immediately after safety checks
            </label>
            <TorrentRetention
              value={retention}
              onChange={setRetention}
              disabled={busy}
              supported={!!list?.retentionSupported}
            />
            <button
              className="primary"
              disabled={busy || changing || !list || !!listError}
            >
              Add torrent
            </button>
            <p className="muted">
              Paused by default. Only approved media locations can be selected.
              Private tracker links are not included in MediaHub events.
            </p>
          </form>
        </Panel>
      </div>
      <SeedboxRSS
        storageId={list?.storageId}
        locations={list?.downloadLocations || []}
        onAdded={reload}
        retentionSupported={list?.retentionSupported}
      />
      <Panel title="Torrents">
        <ErrorBox error={listError} />
        <div className="torrent-table-scroll">
          <table className="torrent-table">
            <thead>
              <tr>
                {[
                  "Name",
                  "Progress",
                  "Status",
                  "Download",
                  "Upload",
                  "Ratio",
                  "ETA",
                  "Size",
                  "Actions",
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list?.items.map((t) => (
                <tr key={t.hash}>
                  <td className="torrent-name">
                    {t.name}
                    <small className="muted">
                      {t.num_seeds ?? 0} seeds · {t.num_leechs ?? 0} peers
                      {t.category ? ` · ${t.category}` : ""}
                      {t.seeding_time
                        ? ` · Seeded ${uptime(t.seeding_time)}`
                        : ""}
                    </small>
                  </td>
                  <td>
                    <progress
                      max={1}
                      value={t.progress}
                      aria-label={`${t.name} progress`}
                    />
                    <small>{(t.progress * 100).toFixed(1)}%</small>
                  </td>
                  <td>{t.state}</td>
                  <td>{bytes(t.dlspeed)}/s</td>
                  <td>{bytes(t.upspeed)}/s</td>
                  <td>{t.ratio.toFixed(2)}</td>
                  <td>{t.eta < 0 || t.eta >= 8640000 ? "—" : uptime(t.eta)}</td>
                  <td>{bytes(t.size)}</td>
                  <td>
                    <div className="torrent-actions">
                      <button
                        disabled={
                          busy || changing || !!listError || !t.actionsAllowed
                        }
                        onClick={() => void action(t.hash, "pause")}
                      >
                        Pause
                      </button>
                      <button
                        disabled={
                          busy || changing || !!listError || !t.actionsAllowed
                        }
                        onClick={() => void action(t.hash, "resume")}
                      >
                        Resume
                      </button>
                      <button
                        disabled={
                          busy || changing || !!listError || !t.actionsAllowed
                        }
                        onClick={() => void action(t.hash, "recheck")}
                      >
                        Recheck
                      </button>
                      <button
                        disabled={
                          busy || changing || !!listError || !t.actionsAllowed
                        }
                        onClick={() => void action(t.hash, "remove")}
                      >
                        Remove job
                      </button>
                      {list?.retentionSupported && (
                        <button
                          disabled={busy || changing || !t.actionsAllowed}
                          onClick={() =>
                            setCleanupEdit({
                              hash: t.hash,
                              name: t.name,
                              rule: t.retention || defaultRetention,
                            })
                          }
                        >
                          Cleanup
                        </button>
                      )}
                      {t.retention && (
                        <small>
                          Cleanup: {t.retention.mode} ·{" "}
                          {t.retention.action === "delete_files"
                            ? "deletes files"
                            : "keeps files"}
                        </small>
                      )}
                      {t.retentionMessage && (
                        <small role="status">{t.retentionMessage}</small>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!list?.items.length && !listError && (
          <p>No torrents yet. Add a magnet link or torrent file above.</p>
        )}
        <p className="muted">
          Remove job always keeps files. Automatic cleanup can delete files only
          when you explicitly select that action. Up to 500 torrents shown.
        </p>
      </Panel>
      {cleanupEdit && (
        <Panel title="Torrent cleanup settings">
          <p style={{ overflowWrap: "anywhere" }}>{cleanupEdit.name}</p>
          <TorrentRetention
            value={cleanupEdit.rule}
            onChange={(rule) => setCleanupEdit({ ...cleanupEdit, rule })}
            disabled={busy}
          />
          <p className="muted">
            Applies to this torrent's existing seeding time and uploaded bytes.
            If its thresholds are already reached, cleanup can run on the next
            check.
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                setError("");
                void api("/seedbox/torrents/retention", "POST", {
                  hash: cleanupEdit.hash,
                  retention: cleanupEdit.rule,
                })
                  .then(() => {
                    setCleanupEdit(null);
                    reload();
                  })
                  .catch((e) => setError(e.message))
                  .finally(() => setBusy(false));
              }}
            >
              Save cleanup settings
            </button>
            <button disabled={busy} onClick={() => setCleanupEdit(null)}>
              Cancel
            </button>
          </div>
        </Panel>
      )}
    </div>
  );
}
