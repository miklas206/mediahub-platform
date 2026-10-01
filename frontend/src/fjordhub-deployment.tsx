import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Link } from "react-router-dom";
import type { FjordHubConfig } from "./fjordhub-commands";

type Deployment = {
  verification?: { state: string; message: string; checkedAt: number };
  id: string;
  state: "running" | "succeeded" | "failed" | "interrupted";
  host: string;
  config: FjordHubConfig;
  message: string;
  logs: string[];
};
const endpoint = "/fjordhub/deployment";

export function FjordHubDeployment({
  config,
  visible,
  onBusy,
}: {
  config: FjordHubConfig;
  visible: boolean;
  onBusy: (busy: boolean) => void;
}) {
  const [job, setJob] = useState<Deployment | null>(null);
  const [host, setHost] = useState("");
  const [port, setPort] = useState("22");
  const [password, setPassword] = useState("");
  const [fingerprint, setFingerprint] = useState("");
  const [verified, setVerified] = useState(false);
  const [inspected, setInspected] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [pending, setPending] = useState(false);
  const requestId = useRef("");
  const consoleRef = useRef<HTMLPreElement>(null);
  const hostEdited = useRef(false);
  const [findingHost, setFindingHost] = useState(false);
  const [hostSource, setHostSource] = useState("");
  const busy = pending || job?.state === "running";
  const needsInspection =
    job?.state === "failed" || job?.state === "interrupted";

  useEffect(() => {
    const controller = new AbortController();
    hostEdited.current = false;
    setHost("");
    setHostSource("");
    setFingerprint("");
    setVerified(false);
    requestId.current = "";
    setFindingHost(true);
    void api<{ host: string | null; source: string | null }>(
      endpoint + "/target?target=" + config.target,
      "GET",
      undefined,
      controller.signal,
    )
      .then((suggestion) => {
        if (
          !controller.signal.aborted &&
          !hostEdited.current &&
          suggestion.host
        ) {
          setHost(suggestion.host);
          setHostSource(suggestion.source || "");
        }
      })
      .catch(() => {
        // Manual entry remains available when discovery cannot reach the Agent.
      })
      .finally(() => {
        if (!controller.signal.aborted) setFindingHost(false);
      });
    return () => controller.abort();
  }, [config.target]);

  useEffect(() => {
    onBusy(busy);
  }, [busy, onBusy]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const status = await api<Deployment | null>(
          endpoint,
          "GET",
          undefined,
          controller.signal,
        );
        setJob(status);
        if (status?.id === requestId.current) requestId.current = "";
        setLoaded(true);
      } catch {
        if (!controller.signal.aborted) setLoaded(false);
      } finally {
        if (!controller.signal.aborted)
          timer = setTimeout(() => void poll(), 2000);
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    const console = consoleRef.current;
    if (
      console &&
      console.scrollHeight - console.scrollTop - console.clientHeight < 150
    )
      console.scrollTop = console.scrollHeight;
  }, [job?.logs]);

  const checkHost = async () => {
    setPending(true);
    setError("");
    setFingerprint("");
    setVerified(false);
    try {
      const result = await api<{ fingerprint: string }>(
        endpoint + "/fingerprint",
        "POST",
        { host, port: Number(port) },
      );
      setFingerprint(result.fingerprint);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  };
  const inspectInstallation = async (remove = false) => {
    if (!job || !verified || !password) return;
    if (
      remove &&
      !window.confirm(
        "Remove this FjordHub deployment's containers? Active use will stop. The LXC, source, app data and settings are kept.",
      )
    )
      return;
    setPending(true);
    setError("");
    try {
      const verification = await api<NonNullable<Deployment["verification"]>>(
        endpoint + "/inspect",
        "POST",
        {
          host,
          port: Number(port),
          fingerprint,
          password,
          jobId: job.id,
          remove,
          confirmedJobId: remove ? job.id : undefined,
        },
      );
      setJob({ ...job, verification });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
      setPassword("");
    }
  };
  const install = async () => {
    setPending(true);
    setError("");
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
      "",
    );
    requestId.current ||= `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    try {
      const result = await api<Deployment>(endpoint, "POST", {
        host,
        port: Number(port),
        fingerprint,
        password,
        config,
        requestId: requestId.current,
        acknowledgedJob: inspected ? job?.id : null,
      });
      setJob(result);
      setInspected(false);
      requestId.current = "";
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
      setPassword("");
    }
  };
  return (
    <>
      {visible && (
        <section className="stack" aria-label="Automatic FjordHub installation">
          <h3>Install directly from MediaHub</h3>
          <p>
            Connect as root to{" "}
            {config.target === "lxc" ? "your Proxmox node" : "the Debian host"}.
            MediaHub runs the displayed installer after you press Install. The
            SSH password is used for this job only and is not saved.
          </p>
          <fieldset disabled={busy} className="store-form-grid">
            <label>
              SSH server IP
              <input
                value={host}
                placeholder={
                  findingHost ? "Finding server IP…" : "Server LAN IP"
                }
                onChange={(e) => {
                  hostEdited.current = true;
                  setHostSource("");
                  setHost(e.target.value);
                  setFingerprint("");
                  setVerified(false);
                  requestId.current = "";
                }}
              />
            </label>
            <label>
              SSH port
              <input
                inputMode="numeric"
                value={port}
                onChange={(e) => {
                  setPort(e.target.value);
                  setFingerprint("");
                  setVerified(false);
                  requestId.current = "";
                }}
              />
            </label>
            <label>
              Root SSH password
              <input
                type="password"
                autoComplete="off"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
          </fieldset>
          <p role="status">
            {findingHost
              ? "Finding the server address from your existing connections…"
              : hostSource === "configured-storage"
                ? "Address filled from your configured storage server. You can change it if Proxmox runs on another host."
                : hostSource === "previous-installation"
                  ? "Address filled from your previous successful installation."
                  : !host
                    ? "No server address could be found automatically. Enter its LAN IP to continue."
                    : ""}
          </p>
          <div className="button-row">
            <button
              type="button"
              disabled={busy || !host}
              onClick={() => void checkHost()}
            >
              Check SSH connection
            </button>
          </div>
          {fingerprint && (
            <div className="notice deployment-fingerprint">
              <strong>Next step: confirm the server identity</strong>
              <p>
                Server fingerprint:{" "}
                <code style={{ overflowWrap: "anywhere" }}>{fingerprint}</code>
              </p>
              <p>
                Compare with the SSH host fingerprint shown on your server. In
                its console:{" "}
                <code>
                  ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
                </code>
              </p>
              <label className="deployment-trust-confirmation">
                <input
                  type="checkbox"
                  aria-label="I recognize and trust this server fingerprint."
                  aria-describedby="deployment-trust-help"
                  checked={verified}
                  disabled={busy}
                  onChange={(e) => setVerified(e.target.checked)}
                />
                <span>
                  <strong>
                    {verified
                      ? "Server confirmed"
                      : "Confirm server to continue"}
                  </strong>
                  <span>I recognize and trust this server fingerprint.</span>
                </span>
              </label>
              <p id="deployment-trust-help">
                {verified
                  ? "Confirmation complete. Enter the root password, then press the install button below."
                  : "After checking the fingerprint, click the confirmation above to enable the next step."}
              </p>
            </div>
          )}
          <p>
            <strong>
              {config.target === "lxc"
                ? `New LXC: ${config.cores} CPU cores, ${Number(config.memory) / 1024} GiB RAM. `
                : "Existing Debian host. "}
            </strong>
            Source: {config.installPath}. Data: {config.dataPath}.
          </p>
          {needsInspection && (
            <label>
              <input
                type="checkbox"
                checked={inspected}
                disabled={busy}
                onChange={(e) => setInspected(e.target.checked)}
              />{" "}
              I have inspected the previous target, confirmed no installer is
              still running and chosen a fresh target for this attempt.
            </label>
          )}
          {!loaded && (
            <p role="status">
              Reconnecting to deployment status. Installation is disabled until
              the status is known.
            </p>
          )}
          <button
            type="button"
            className="primary"
            disabled={
              busy ||
              !loaded ||
              !verified ||
              !password ||
              (needsInspection && !inspected)
            }
            onClick={() => void install()}
          >
            {pending
              ? "Working..."
              : busy
                ? "Installation in progress…"
                : config.target === "lxc"
                  ? "Create LXC and install FjordHub"
                  : "Install FjordHub"}
          </button>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </section>
      )}
      {job && (
        <section className="stack" aria-label="FjordHub deployment status">
          <strong>
            {job.state === "running"
              ? "Installing FjordHub"
              : job.state === "succeeded"
                ? "Previous installation completed"
                : "Installation needs attention"}{" "}
            · {job.host}
          </strong>
          <p role="status">
            {job.state === "succeeded"
              ? "This is the previous installation result, not proof that FjordHub is still installed."
              : job.message}
          </p>
          {job.verification && (
            <p role="status">
              <strong>{job.verification.state}</strong>:{" "}
              {job.verification.message} Last checked:{" "}
              {new Date(job.verification.checkedAt * 1000).toLocaleString()}
            </p>
          )}
          {job.state !== "running" && (
            <>
              <p>
                Enter the SSH password and verify the host fingerprint above to
                check the actual installation. No password is stored.
              </p>
              <div className="runtime-toolbar">
                <button
                  disabled={busy || !verified || !password || host !== job.host}
                  onClick={() => void inspectInstallation()}
                >
                  Check actual installation
                </button>
                <Link to="/store/fjordhub/uninstall">
                  Uninstall FjordHub — preserve external media
                </Link>
              </div>
            </>
          )}
          {job.state === "running" && (
            <p>
              You can leave this page and return to see progress. Keep MediaHub
              running until installation finishes.
            </p>
          )}
          <details open>
            <summary>Installation console</summary>
            <pre
              ref={consoleRef}
              className="install-command-block"
              aria-label="FjordHub installation console"
            >
              {job.logs.join("\n") || "Waiting for SSH output…"}
            </pre>
          </details>
        </section>
      )}
    </>
  );
}
