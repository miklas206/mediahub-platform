import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ErrorBox, Panel } from "./phase2";
import { bytes, uptime } from "./format";

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
};
type DownloadLocation = { id: string; label: string };
type Listing = {
  items: Torrent[];
  storageId: string;
  downloadLocations?: DownloadLocation[];
  limit: number;
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
};

export function SeedboxDaily({
  externalIp,
  forwarding,
}: {
  externalIp?: string | null;
  forwarding?: string;
}) {
  const [list, setList] = useState<Listing | null>(null),
    [location, setLocation] = useState<Locations | null>(null);
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
          ? v.downloadLocations
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
      await api("/seedbox/locations", "POST", { country: selected, server });
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
                    MediaHub Downloads · {item.label}
                  </option>
                ))}
              </select>
            </label>
            {downloadLocationsSupported === false && (
              <p className="muted">
                This Seedbox Agent still supports the Downloads top folder only.
                Install the matching Agent update to enable folder choices.
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
            <button
              className="primary"
              disabled={busy || changing || !list || !!listError}
            >
              Add torrent
            </button>
            <p className="muted">
              Paused by default. Only existing folders directly inside the
              approved Downloads storage can be selected. Private tracker links
              are not included in MediaHub events.
            </p>
          </form>
        </Panel>
      </div>
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
          Remove job always keeps files. File deletion is intentionally not
          available here. Up to 500 torrents shown.
        </p>
      </Panel>
    </div>
  );
}
