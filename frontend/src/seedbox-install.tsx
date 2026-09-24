import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "./api";
import { ErrorBox, Panel } from "./phase2";

type Settings = {
  incompleteDownloads: boolean;
  maxConnections: number;
  maxConnectionsPerTorrent: number;
  maxActiveDownloads: number;
  listenPort: number;
  networkInterface: string;
};
type Wizard = {
  revision: number;
  step: number;
  steps: string[];
  busy: boolean;
  installation: {
    hostId: string;
    downloadsStorageId: string;
    provider: string;
    protocol: string;
    uid: number;
    gid: number;
    webPort: number;
    torrentMemoryMiB: number;
    installationId: string;
  };
  qBittorrent: Settings;
  portForwardingAcknowledged: boolean;
  vpnConfigured: boolean;
  clientConfigured: boolean;
  runtimeCredentialConfigured: boolean;
  preflight: { state: string; digest?: string; message?: string } | null;
  transaction: {
    state: string;
    failedStep?: string;
    steps: { id: string; state: string }[];
  };
};
type Plan = {
  digest: string;
  blockers: string[];
  storage: { mountedAndVerified: boolean; source: string };
  compose: unknown;
  healthChecks: string[];
};

export function SeedboxInstallPage() {
  const { appId } = useParams();
  const [data, setData] = useState<Wizard | null>(null),
    [plan, setPlan] = useState<Plan | null>(null);
  const [failure, setFailure] = useState(""),
    [busy, setBusy] = useState(false);
  const [disconnected, setDisconnected] = useState(false);
  const [targets, setTargets] = useState<{
    bound: boolean;
    hosts: { id: string; name: string }[];
  } | null>(null);
  const [selectedHost, setSelectedHost] = useState("");
  useEffect(() => {
    void api<{ bound: boolean; hosts: { id: string; name: string }[] }>(
      "/seedbox/wizard/targets",
    )
      .then(setTargets)
      .catch((e) => setFailure(e.message));
  }, []);
  async function delegate() {
    setBusy(true);
    setFailure("");
    try {
      await api("/seedbox/wizard/target", "POST", { hostId: selectedHost });
      setTargets((t) => (t ? { ...t, bound: true } : t));
      await refresh();
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const refresh = useCallback(async () => {
    setData(await api<Wizard>("/seedbox/wizard"));
  }, []);
  useEffect(() => {
    let active = true;
    const poll = () =>
      api<Wizard>("/seedbox/wizard")
        .then((value) => {
          if (active) {
            setData(value);
            setDisconnected(false);
          }
        })
        .catch(() => {
          if (active) setDisconnected(true);
        });
    void poll();
    const timer = setInterval(poll, 2500);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  async function perform(path: string, body?: unknown) {
    setBusy(true);
    setFailure("");
    try {
      await api("/seedbox/wizard/" + path, "POST", body);
      await refresh();
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function review() {
    setBusy(true);
    setFailure("");
    try {
      setPlan(await api<Plan>("/seedbox/wizard/review"));
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function importVPN(file: File | undefined, input: HTMLInputElement) {
    if (!file || !data) return;
    if (file.size > 65536) {
      setFailure("Configuration must be at most 64 KiB.");
      input.value = "";
      return;
    }
    try {
      await perform(data.step === 12 ? "rotate/vpn" : "vpn", {
        revision: data.revision,
        vpnConfig: await file.text(),
      });
    } finally {
      input.value = "";
    }
  }
  const running = busy || data?.busy;
  const locked = data?.transaction.state === "ManualIntervention";
  const displayStep =
    data?.transaction.state === "Installing" ? 10 : (data?.step ?? 0);
  return (
    <div className="stack seedbox-wizard">
      <Link to={appId ? `/apps/${appId}` : "/apps"}>← Apps</Link>
      {targets && !targets.bound && (
        <Panel title="Choose your dedicated Seedbox host">
          <p>
            Protected downloads run separately from MediaHub and Plex. Select a
            paired host with approved Downloads storage.
          </p>
          {targets.hosts.length ? (
            <>
              <label>
                Host
                <select
                  value={selectedHost}
                  onChange={(e) => setSelectedHost(e.target.value)}
                >
                  <option value="">Choose host</option>
                  {targets.hosts.map((h) => (
                    <option key={h.id} value={h.id}>
                      {h.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                disabled={busy || !selectedHost}
                onClick={() => void delegate()}
              >
                Use this host
              </button>
            </>
          ) : (
            <p>
              No paired host yet. <Link to="/hosts">Connect a host first</Link>,
              then return here.
            </p>
          )}
        </Panel>
      )}
      <div>
        <p className="eyebrow">ISOLATED SEEDBOX · GUIDED INSTALLATION</p>
        <h1>A safe start, every step verified</h1>
        <p>
          Configuration stays on your Agent. Reload or return later without
          losing progress.
        </p>
      </div>
      <ErrorBox error={failure} />
      {disconnected && (
        <ErrorBox error="Agent unavailable. Progress remains on the server; do not start a second installation." />
      )}
      {data && (
        <>
          <nav aria-label="Installation progress">
            <ol className="wizard-steps">
              {data.steps.map((name, index) => (
                <li
                  key={name}
                  aria-current={index === displayStep ? "step" : undefined}
                  className={
                    index < displayStep
                      ? "complete"
                      : index === displayStep
                        ? "current"
                        : ""
                  }
                >
                  <span>{index < displayStep ? "✓" : index + 1}</span>
                  {name}
                </li>
              ))}
            </ol>
          </nav>
          <Panel title={`${displayStep + 1} · ${data.steps[displayStep]}`}>
            <p role="status">
              {data.transaction.state} · VPN:{" "}
              {data.vpnConfigured ? "Configured" : "Not configured"} · Client
              credentials:{" "}
              {data.clientConfigured ? "Configured" : "Not configured"}
            </p>
            {data.step === 0 && (
              <>
                <p>
                  Only the delegated host and downloads storage can be used.
                  Existing media is never moved or deleted.
                </p>
                {data.runtimeCredentialConfigured && (
                  <>
                    <p>
                      Already running? Verify and adopt without recreating
                      containers.
                    </p>
                    <button disabled={running} onClick={() => perform("adopt")}>
                      Verify & adopt existing runtime
                    </button>
                  </>
                )}
              </>
            )}
            {data.step === 1 && (
              <>
                <label>
                  Authorized target{" "}
                  <input readOnly value={data.installation.hostId} />
                </label>
                <p>
                  This Agent is independently paired with internal HTTPS. This
                  installation cannot target MediaHub Core.
                </p>
              </>
            )}
            {data.step === 2 && (
              <>
                <label>
                  Logical downloads storage{" "}
                  <input
                    readOnly
                    value={data.installation.downloadsStorageId}
                  />
                </label>
                <p>
                  The Agent resolves this mapping to its authorized NFS mount.
                  Movies and TV are not granted. Mount identity and writable
                  space are checked live.
                </p>
              </>
            )}
            {data.step === 3 && (
              <>
                <p>
                  {data.installation.provider} / {data.installation.protocol}
                </p>
                <p>
                  Use a dedicated Proton P2P WireGuard profile with NAT-PMP
                  enabled. Other provisioning adapters are not enabled.
                </p>
              </>
            )}
            {data.step === 4 && (
              <>
                <label>
                  Import private WireGuard configuration{" "}
                  <input
                    type="file"
                    accept=".conf"
                    disabled={running}
                    onChange={(e) =>
                      void importVPN(e.target.files?.[0], e.target)
                    }
                  />
                </label>
                <p>
                  The profile is encrypted on the Agent. Only protected RAM
                  contains runtime plaintext. The contents are never returned to
                  this page.
                </p>
              </>
            )}
            {data.step === 5 && (
              <>
                <p>
                  A forwarded port is leased through the VPN and synchronized
                  with qBittorrent. No router ports are opened.
                </p>
                <label>
                  <input
                    type="checkbox"
                    checked={data.portForwardingAcknowledged}
                    disabled={running}
                    onChange={(e) =>
                      perform("configure", {
                        revision: data.revision,
                        installation: data.installation,
                        qBittorrent: data.qBittorrent,
                        portForwardingAcknowledged: e.target.checked,
                      })
                    }
                  />{" "}
                  My dedicated P2P configuration has NAT-PMP enabled.
                </label>
              </>
            )}
            {data.step === 6 && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const fields = new FormData(e.currentTarget);
                  void perform("configure", {
                    revision: data.revision,
                    installation: data.installation,
                    portForwardingAcknowledged: data.portForwardingAcknowledged,
                    qBittorrent: {
                      ...data.qBittorrent,
                      maxConnections: Number(fields.get("connections")),
                      maxActiveDownloads: Number(fields.get("downloads")),
                    },
                  });
                }}
              >
                <label>
                  Maximum connections{" "}
                  <input
                    name="connections"
                    type="number"
                    min={10}
                    max={500}
                    defaultValue={data.qBittorrent.maxConnections}
                  />
                </label>
                <label>
                  Active downloads{" "}
                  <input
                    name="downloads"
                    type="number"
                    min={1}
                    max={5}
                    defaultValue={data.qBittorrent.maxActiveDownloads}
                  />
                </label>
                <p>
                  Network binding: tun0 · Memory limit:{" "}
                  {data.installation.torrentMemoryMiB} MiB · App UID/GID:{" "}
                  {data.installation.uid}/{data.installation.gid}. New torrents
                  start stopped.
                </p>
                <button disabled={running}>Save client settings</button>
              </form>
            )}
            {data.step === 7 && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const form = e.currentTarget,
                    fields = new FormData(form);
                  const body = {
                    revision: data.revision,
                    webUsername: fields.get("username"),
                    webPassword: fields.get("password"),
                  };
                  form.reset();
                  void perform("client", body);
                }}
              >
                <label>
                  qBittorrent username{" "}
                  <input
                    name="username"
                    required
                    pattern="[A-Za-z0-9_.\-]{1,64}"
                    autoComplete="off"
                  />
                </label>
                <label>
                  qBittorrent password{" "}
                  <input
                    name="password"
                    type="password"
                    required
                    minLength={16}
                    maxLength={256}
                    autoComplete="new-password"
                  />
                </label>
                <p>
                  Use a unique password. Credentials are sent only over HTTPS,
                  stored encrypted and never shown again.
                </p>
                <button disabled={running}>Save encrypted credentials</button>
              </form>
            )}
            {(data.step === 8 || data.step === 9) && (
              <>
                <button disabled={running} onClick={review}>
                  Load current reviewed plan
                </button>
                {plan && (
                  <>
                    <p>
                      Storage: {plan.storage.source} · Mounted:{" "}
                      {plan.storage.mountedAndVerified
                        ? "Verified"
                        : "Not verified"}
                    </p>
                    {plan.blockers.map((item) => (
                      <p role="alert" key={item}>
                        {item}
                      </p>
                    ))}
                    <details>
                      <summary>Exact runtime plan — no secrets</summary>
                      <pre>{JSON.stringify(plan.compose, null, 2)}</pre>
                    </details>
                    <p>Checks: {plan.healthChecks.join(" → ")}</p>
                  </>
                )}
                {data.preflight?.message && (
                  <p role="alert">{data.preflight.message}</p>
                )}
                {data.step === 9 && (
                  <button
                    disabled={running || !plan || locked}
                    onClick={() =>
                      perform("preflight", {
                        revision: data.revision,
                        reviewedPlanDigest: plan?.digest,
                      })
                    }
                  >
                    Run live preflight
                  </button>
                )}
              </>
            )}
            {data.step === 10 && (
              <>
                <p>
                  Preflight passed for this configuration. Installation repeats
                  safety checks and creates only owned runtime resources.
                </p>
                <button
                  disabled={running || locked}
                  onClick={() =>
                    perform("install", {
                      revision: data.revision,
                      reviewedPlanDigest: data.preflight?.digest,
                    })
                  }
                >
                  Install & verify Seedbox
                </button>
              </>
            )}
            {data.step === 11 && (
              <p>
                Installation continues on the Agent even if this page is closed.
                Do not start another installation.
              </p>
            )}
            {data.transaction.steps.length > 0 && (
              <ol>
                {data.transaction.steps.map((row) => (
                  <li key={row.id}>
                    {row.id.replaceAll("_", " ")} — {row.state}
                  </li>
                ))}
              </ol>
            )}
            {locked && (
              <>
                <p role="alert">
                  The previous operation needs reconciliation. Automatic retry
                  is blocked to protect existing runtime and data.
                </p>
                <button disabled={running} onClick={() => perform("rollback")}>
                  Remove only runtime owned by the failed transaction
                </button>
              </>
            )}
            {data.step === 12 && (
              <>
                <p>
                  Installation safety gates passed. Use live app status for
                  current VPN, storage and client health.
                </p>
                <Link to={appId ? `/apps/${appId}` : "/apps"}>
                  Open installed apps →
                </Link>
              </>
            )}
            {data.step === 12 && (
              <details>
                <summary>Rotate private credentials</summary>
                <p>
                  VPN rotation stops qBittorrent until the new tunnel,
                  forwarding and storage pass all guards. A failed rotation
                  blocks automatic restart.
                </p>
                <label>
                  New dedicated WireGuard profile{" "}
                  <input
                    type="file"
                    accept=".conf"
                    disabled={running}
                    onChange={(e) =>
                      void importVPN(e.target.files?.[0], e.target)
                    }
                  />
                </label>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    const form = e.currentTarget,
                      fields = new FormData(form);
                    const body = {
                      revision: data.revision,
                      webUsername: fields.get("username"),
                      webPassword: fields.get("password"),
                    };
                    form.reset();
                    void perform("rotate/client", body);
                  }}
                >
                  <label>
                    Client username{" "}
                    <input name="username" required autoComplete="off" />
                  </label>
                  <label>
                    New unique password{" "}
                    <input
                      name="password"
                      type="password"
                      required
                      minLength={16}
                      maxLength={256}
                      autoComplete="new-password"
                    />
                  </label>
                  <button disabled={running}>
                    Rotate & verify client credential
                  </button>
                </form>
              </details>
            )}
            {data.step <= 10 && (
              <div className="wizard-actions">
                <button
                  disabled={running || data.step === 0 || locked}
                  onClick={() =>
                    perform("advance", {
                      revision: data.revision,
                      direction: "back",
                    })
                  }
                >
                  Back
                </button>
                {data.step < 9 && (
                  <button
                    disabled={
                      running ||
                      locked ||
                      (data.step === 4 && !data.vpnConfigured) ||
                      (data.step === 5 && !data.portForwardingAcknowledged) ||
                      (data.step === 7 && !data.clientConfigured)
                    }
                    onClick={() =>
                      perform("advance", {
                        revision: data.revision,
                        direction: "next",
                      })
                    }
                  >
                    Save & continue →
                  </button>
                )}
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
