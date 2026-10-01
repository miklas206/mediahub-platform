import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { Panel } from "./phase2";

type Mount = { slot: string; source: string; path: string };
type Plan = {
  state: string;
  message?: string;
  digest: string;
  ctid: string;
  deleteDisks: Mount[];
  preserveMounts: Mount[];
  containers: string[];
  accounts: string[];
};
type Deployment = {
  id: string;
  host: string;
  state: string;
  config: { target: string };
  uninstall?: Plan;
};
const endpoint = "/fjordhub/deployment";

export function FjordHubUninstallPage() {
  const [job, setJob] = useState<Deployment | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [port, setPort] = useState("22");
  const [password, setPassword] = useState("");
  const [fingerprint, setFingerprint] = useState("");
  const [trusted, setTrusted] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [external, setExternal] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    void api<Deployment | null>(endpoint, "GET", undefined, controller.signal)
      .then((result) => {
        setJob(result);
        setLoaded(true);
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, []);

  const checkHost = async () => {
    if (!job) return;
    setPending(true);
    setError("");
    setTrusted(false);
    setFingerprint("");
    setPlan(null);
    try {
      const result = await api<{ fingerprint: string }>(
        endpoint + "/fingerprint",
        "POST",
        {
          host: job.host,
          port: Number(port),
        },
      );
      setFingerprint(result.fingerprint);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  };

  const inspectOrRemove = async (remove: boolean) => {
    if (!job || !trusted || !password) return;
    setPending(true);
    setError("");
    try {
      const result = await api<Plan>(endpoint + "/uninstall", "POST", {
        host: job.host,
        port: Number(port),
        password,
        fingerprint,
        jobId: job.id,
        remove,
        confirmedJobId: remove ? job.id : undefined,
        planDigest: remove ? plan?.digest : undefined,
        externalMediaConfirmed: remove && external,
      });
      setPlan(result);
      setJob({ ...job, uninstall: result });
      setExternal(false);
      setConfirmation("");
    } catch (e) {
      setPlan(null);
      setError((e as Error).message);
    } finally {
      setPending(false);
      if (remove) setPassword("");
    }
  };

  const removed = job?.uninstall?.state === "removed";
  const supported = job?.config.target === "lxc" && job.state !== "running";
  return (
    <div className="stack">
      <Link to="/store">← Back to App Store</Link>
      <h2>Uninstall FjordHub</h2>
      <p>
        Remove the dedicated FjordHub LXC, its apps (including FjordFlix),
        Docker data and settings. External media on shared storage are
        preserved.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!loaded && !error && (
        <p role="status">Loading the recorded installation…</p>
      )}
      {loaded && !job && (
        <p className="notice">
          No MediaHub deployment is recorded. Automatic removal is unavailable
          because ownership cannot be verified.
        </p>
      )}
      {removed && (
        <p className="notice" role="status">
          {job.uninstall?.message}
        </p>
      )}
      {job && !removed && (
        <Panel title="Review this installation before removal">
          <div className="stack">
            <p>
              Recorded Proxmox server: <strong>{job.host}</strong>
            </p>
            {!supported ? (
              <p className="notice">
                Wait for an active installation to finish. Full automatic
                removal is only supported for a dedicated LXC created through
                MediaHub; shared Debian hosts require manual cleanup.
              </p>
            ) : (
              <>
                {job.uninstall?.state === "removing" && (
                  <p className="notice">
                    A removal was started. If it is still running, a new check
                    will be refused. If interrupted, inspect again to determine
                    the actual state.
                  </p>
                )}
                {job.uninstall?.state === "incomplete" && (
                  <p className="notice">{job.uninstall.message}</p>
                )}
                <fieldset disabled={pending} className="store-form-grid">
                  <label>
                    SSH port
                    <input
                      inputMode="numeric"
                      value={port}
                      onChange={(e) => {
                        setPort(e.target.value);
                        setFingerprint("");
                        setTrusted(false);
                        setPlan(null);
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
                <p>
                  The password is used for this operation only and is not saved.
                  Keep MediaHub running until removal finishes.
                </p>
                <button disabled={pending} onClick={() => void checkHost()}>
                  Check SSH connection
                </button>
                {fingerprint && (
                  <div className="notice stack">
                    <p>
                      Compare this fingerprint with your Proxmox server:{" "}
                      <code style={{ overflowWrap: "anywhere" }}>
                        {fingerprint}
                      </code>
                    </p>
                    <label>
                      <input
                        type="checkbox"
                        disabled={pending}
                        checked={trusted}
                        onChange={(e) => setTrusted(e.target.checked)}
                      />{" "}
                      I recognize and trust this server fingerprint.
                    </label>
                  </div>
                )}
                <button
                  disabled={pending || !trusted || !password}
                  onClick={() => void inspectOrRemove(false)}
                >
                  {pending ? "Working…" : "Preview uninstall"}
                </button>
                {plan?.state === "ready" && (
                  <section className="stack" aria-label="Uninstall plan">
                    <h3>Remove LXC {plan.ctid} permanently</h3>
                    <p>These system and app-data disks will be deleted:</p>
                    <ul>
                      {plan.deleteDisks.map((disk) => (
                        <li key={disk.slot}>
                          <code>{disk.source}</code> — {disk.path}
                        </li>
                      ))}
                    </ul>
                    <p>
                      Apps and containers:{" "}
                      {plan.containers.join(", ") || "None found"}.
                    </p>
                    <p>
                      Dedicated Proxmox accounts:{" "}
                      {plan.accounts.join(", ") || "None found"}.
                    </p>
                    <h3>External storage is preserved</h3>
                    {plan.preserveMounts.length ? (
                      <ul>
                        {plan.preserveMounts.map((mount) => (
                          <li key={mount.slot}>
                            <code>{mount.source}</code> → {mount.path}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>
                        No external bind mounts were found in this LXC. Shared
                        media elsewhere are untouched.
                      </p>
                    )}
                    <p>
                      The matching MediaHub connection is removed. Installation
                      history is retained. Extra managed disks, snapshots or
                      detected media on internal disks block removal.
                    </p>
                    <label>
                      <input
                        type="checkbox"
                        disabled={pending}
                        checked={external}
                        onChange={(e) => setExternal(e.target.checked)}
                      />{" "}
                      All my media are on external storage. The system and
                      app-data disks listed above contain no media I want to
                      keep.
                    </label>
                    <label>
                      Type LXC ID {plan.ctid} to confirm
                      <input
                        disabled={pending}
                        value={confirmation}
                        onChange={(e) => setConfirmation(e.target.value)}
                      />
                    </label>
                    <button
                      disabled={
                        pending ||
                        !trusted ||
                        !password ||
                        !external ||
                        confirmation !== plan.ctid
                      }
                      onClick={() => void inspectOrRemove(true)}
                    >
                      Permanently uninstall FjordHub
                    </button>
                  </section>
                )}
              </>
            )}
          </div>
        </Panel>
      )}
    </div>
  );
}
