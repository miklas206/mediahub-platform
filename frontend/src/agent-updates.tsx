import { useEffect, useState } from "react";
import { api } from "./api";
import { Panel, ErrorBox } from "./phase2";
import { OperationProgress, type OperationState } from "./operation-progress";
import { runUpdateAll, updateAllPlan } from "./update-all";

type Check = {
  host: string;
  installedVersion: string;
  latestCommit: string | null;
  updateAvailable: boolean;
  installReady: boolean;
  message: string;
};
type Job = { state: string; message: string; logs: string[] };
export function AgentUpdates({
  onChange,
  busy,
}: {
  onChange: () => void;
  busy: boolean;
}) {
  const [check, setCheck] = useState<Check>();
  const [error, setError] = useState("");
  const [password, setPassword] = useState("");
  const [port, setPort] = useState(22);
  const [fingerprint, setFingerprint] = useState("");
  const [trusted, setTrusted] = useState(false);
  const [working, setWorking] = useState(false);
  const [operation, setOperation] = useState<OperationState>();
  async function reload() {
    setCheck(await api<Check>("/updates/seedbox-agent"));
    onChange();
  }
  useEffect(() => {
    let active = true;
    let lastState = "";
    async function load() {
      try {
        const data = await api<Check>("/updates/seedbox-agent");
        if (active) setCheck(data);
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    }
    void load();
    async function poll() {
      try {
        const job = await api<Job>("/updates/seedbox-agent/operation");
        if (!active || job.state === "idle") return;
        if (job.state === "succeeded" && lastState !== "succeeded") {
          await load();
        }
        lastState = job.state;
        const running = [
          "running",
          "building",
          "installing",
          "verifying",
          "rolling_back",
        ].includes(job.state);
        setOperation({
          title: "Seedbox Agent update",
          status: running
            ? "running"
            : job.state === "succeeded"
              ? "success"
              : "error",
          progress:
            job.state === "succeeded"
              ? 100
              : job.state === "verifying"
                ? 90
                : job.state === "installing"
                  ? 75
                  : 20,
          message: job.message,
          console: job.logs,
          details: [],
          steps: [],
        });
      } catch {
        if (active)
          setOperation((previous) =>
            previous?.status === "running"
              ? {
                  ...previous,
                  message:
                    "Connection interrupted; waiting for Agent update status...",
                }
              : previous,
          );
      }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  async function act(action: () => Promise<void>) {
    setWorking(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setWorking(false);
    }
  }
  const disabled = working || busy || operation?.status === "running";
  return (
    <Panel title="Seedbox Agent">
      <ErrorBox error={error} />
      <div className="runtime-row">
        <span>Installed Agent code</span>
        <strong>
          {check?.installedVersion?.slice(0, 12) || "Not checked"}
        </strong>
      </div>
      <div className="runtime-row">
        <span>Latest on GitHub main</span>
        <strong>{check?.latestCommit?.slice(0, 12) || "Not checked"}</strong>
      </div>
      <p className="muted">
        {check?.message || "Checks the separately paired Seedbox Agent."}
      </p>
      <button disabled={disabled} onClick={() => void act(reload)}>
        Check Agent update
      </button>
      {check?.updateAvailable && (
        <fieldset disabled={disabled}>
          <legend>Prepare Agent update</legend>
          <p>
            SSH server: <strong>{check.host}</strong> (paired Seedbox host).
            Enter this host's root password. It is kept only in memory for one
            update, up to 15 minutes.
          </p>
          <label>
            SSH port
            <input
              type="number"
              min={1}
              max={65535}
              value={port}
              onChange={(e) => {
                setPort(Number(e.target.value));
                setFingerprint("");
                setTrusted(false);
              }}
            />
          </label>
          <button
            onClick={() =>
              void act(async () => {
                const data = await api<{ fingerprint: string }>(
                  "/updates/seedbox-agent/fingerprint",
                  "POST",
                  { port },
                );
                setFingerprint(data.fingerprint);
                setTrusted(false);
              })
            }
          >
            Read SSH fingerprint
          </button>
          {fingerprint && (
            <>
              <p style={{ overflowWrap: "anywhere" }}>{fingerprint}</p>
              <p className="muted">
                Compare this with the SSH host fingerprint on the Seedbox
                server.
              </p>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={trusted}
                  onChange={(e) => setTrusted(e.target.checked)}
                />
                I recognize and trust this server fingerprint
              </label>
            </>
          )}
          <label>
            Root SSH password
            <input
              type="password"
              autoComplete="off"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button
            disabled={!trusted || !password}
            onClick={() =>
              void act(async () => {
                await api("/updates/seedbox-agent/prepare", "POST", {
                  port,
                  fingerprint,
                  password,
                });
                setPassword("");
                await reload();
              })
            }
          >
            Prepare SSH for update
          </button>
          <p>
            {check.installReady
              ? "SSH is ready. Use Update Agent or Update all."
              : "Prepare SSH to enable installation."}
          </p>
          <button
            className="primary"
            disabled={!check.installReady}
            onClick={() =>
              void act(async () => {
                await runUpdateAll(
                  updateAllPlan(
                    [
                      {
                        id: "seedbox-agent",
                        name: "Seedbox Agent",
                        updateAvailable: true,
                      },
                    ],
                    [],
                  ),
                  api,
                  setOperation,
                );
                await reload();
              })
            }
          >
            Update Agent
          </button>
        </fieldset>
      )}
      {operation && <OperationProgress operation={operation} />}
    </Panel>
  );
}
