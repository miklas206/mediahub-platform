import { translateText, t } from "./i18n";

import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { AgentAccessSetup } from "./agent-access-setup";
import { Panel, ErrorBox } from "./phase2";
import { OperationProgress, type OperationState } from "./operation-progress";

type Check = {
  host: string;
  installedVersion: string;
  latestCommit: string | null;
  updateAvailable: boolean;
  installReady: boolean;
  credentialsStored?: boolean;
  message: string;
};
type Job = {
  state: string;
  message: string;
  logs: string[];
  errorCode?: string;
};
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
  const [authMethod, setAuthMethod] = useState("password");
  const [privateKey, setPrivateKey] = useState("");
  const [remember, setRemember] = useState(false);
  const [port, setPort] = useState(22);
  const [fingerprint, setFingerprint] = useState("");
  const [trusted, setTrusted] = useState(false);
  const [fingerprintChanged, setFingerprintChanged] = useState(false);
  const fingerprintVerified = useRef(false);
  const [working, setWorking] = useState(false);
  const [operation, setOperation] = useState<OperationState>();
  const startGeneration = useRef(0);
  const starting = useRef(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  async function reload() {
    setCheck(await api<Check>("/updates/seedbox-agent"));
    onChange();
  }
  useEffect(() => {
    let active = true;
    let lastState = "";
    let timer: number | undefined;
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
      const generation = startGeneration.current;
      try {
        if (starting.current) return;
        const job = await api<Job>("/updates/seedbox-agent/operation");
        if (
          !active ||
          starting.current ||
          generation !== startGeneration.current ||
          job.state === "idle"
        )
          return;
        if (job.state === "succeeded" && lastState !== "succeeded") {
          await load();
          if (active) onChangeRef.current();
        }
        if (!active || generation !== startGeneration.current) return;
        lastState = job.state;
        setFingerprintChanged(
          !fingerprintVerified.current &&
            job.errorCode === "ssh_host_key_changed",
        );
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
        if (
          active &&
          !starting.current &&
          generation === startGeneration.current
        )
          setOperation((previous) =>
            previous?.status === "running"
              ? {
                  ...previous,
                  connectionLost: true,
                  message:
                    "Connection interrupted; waiting for Agent update status...",
                }
              : previous,
          );
      } finally {
        if (active) timer = window.setTimeout(() => void poll(), 2000);
      }
    }
    void poll();
    return () => {
      active = false;
      window.clearTimeout(timer);
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
    <Panel title={t("Seedbox Agent")}>
      <ErrorBox error={error} />
      {error && !check?.credentialsStored && (
        <button
          disabled={working || busy}
          onClick={() =>
            void act(async () => {
              await api("/updates/seedbox-agent/credentials", "DELETE");
              await reload();
            })
          }
        >
          {t("Forget saved SSH access")}
        </button>
      )}
      <div className="runtime-row">
        <span>{t("Installed Agent code")}</span>
        <strong>
          {check?.installedVersion?.slice(0, 12) || t("Not checked")}
        </strong>
      </div>
      <div className="runtime-row">
        <span>{t("Latest on GitHub main")}</span>
        <strong>{check?.latestCommit?.slice(0, 12) || t("Not checked")}</strong>
      </div>
      {!check?.latestCommit && (
        <p className="muted">
          {translateText(check?.message) ||
            t("Checking the paired Seedbox Agent...")}
        </p>
      )}
      <div className="button-row">
        <button disabled={disabled} onClick={() => void act(reload)}>
          {t("Check Agent update")}
        </button>
        {check?.updateAvailable && (
          <button
            className="primary"
            disabled={disabled || !check.installReady}
            onClick={() =>
              void act(async () => {
                starting.current = true;
                fingerprintVerified.current = false;
                startGeneration.current += 1;
                try {
                  const job = await api<Job>(
                    "/updates/seedbox-agent/install",
                    "POST",
                  );
                  setOperation({
                    title: "Seedbox Agent update",
                    status: "running",
                    progress: 20,
                    message: job.message,
                    console: job.logs,
                    details: [],
                    steps: [],
                  });
                } finally {
                  starting.current = false;
                  startGeneration.current += 1;
                }
              })
            }
          >
            {t("Update Agent")}
          </button>
        )}
      </div>
      {check?.credentialsStored && (
        <div className="button-row">
          <span className="muted">
            {t("SSH access saved encrypted on this MediaHub server.")}
          </span>
          <button
            disabled={disabled}
            onClick={() =>
              void act(async () => {
                await api("/updates/seedbox-agent/credentials", "DELETE");
                setRemember(false);
                await reload();
              })
            }
          >
            {t("Forget saved SSH access")}
          </button>
          <button
            disabled={disabled}
            onClick={() =>
              void act(async () => {
                await api("/updates/seedbox-agent/prepare-saved", "POST");
                await reload();
              })
            }
          >
            {t("Verify saved SSH access")}
          </button>
        </div>
      )}
      {fingerprintChanged && (
        <p className="muted">
          {t(
            "The saved SSH fingerprint no longer matches. Open SSH settings, read the fingerprint, compare it on the Seedbox server, and verify saved access with the confirmed fingerprint.",
          )}
        </p>
      )}
      {check && !check.credentialsStored && (
        <AgentAccessSetup disabled={disabled} onReady={reload} />
      )}
      {check?.updateAvailable && (
        <details className="agent-update-setup">
          <summary>
            {check.credentialsStored
              ? t("SSH settings")
              : t("Advanced: use existing SSH access")}
          </summary>
          <fieldset disabled={disabled}>
            <legend>{t("Prepare Agent update")}</legend>
            <>
              <p>
                {t("SSH server: ")}
                <strong>{check.host}</strong>
                {t(
                  " (paired Seedbox host). Use a root password or an authorized SSH private key. Save access encrypted on MediaHub or use it for this update only.",
                )}
              </p>
              <label>
                {t("SSH port")}
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
                {t("Read SSH fingerprint")}
              </button>
              {fingerprint && (
                <>
                  <p style={{ overflowWrap: "anywhere" }}>{fingerprint}</p>
                  <p className="muted">
                    {t(
                      "Compare this with the SSH host fingerprint on the Seedbox server.",
                    )}
                  </p>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={trusted}
                      onChange={(e) => setTrusted(e.target.checked)}
                    />
                    {t("I recognize and trust this server fingerprint")}
                  </label>
                </>
              )}
              {!check.credentialsStored && (
                <>
                  <label>
                    {t("Authentication")}
                    <select
                      value={authMethod}
                      onChange={(e) => {
                        setAuthMethod(e.target.value);
                        setPassword("");
                        setPrivateKey("");
                      }}
                    >
                      <option value="password">{t("Root password")}</option>
                      <option value="key">{t("SSH private key")}</option>
                    </select>
                  </label>
                  {authMethod === "key" ? (
                    <label>
                      {t("SSH private key")}
                      <textarea
                        rows={5}
                        autoComplete="off"
                        spellCheck={false}
                        value={privateKey}
                        onChange={(e) => setPrivateKey(e.target.value)}
                      />
                      <span className="muted">
                        {t(
                          "The matching public key must be authorized for root on the Seedbox host. Paste an unencrypted OpenSSH or PEM key; saved access is encrypted by MediaHub.",
                        )}
                      </span>
                    </label>
                  ) : (
                    <label>
                      {t("Root SSH password")}
                      <input
                        type="password"
                        autoComplete="off"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                    </label>
                  )}
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={remember}
                      onChange={(e) => setRemember(e.target.checked)}
                    />
                    {t(
                      "Remember SSH access for future Agent updates (encrypted)",
                    )}
                  </label>
                  <button
                    disabled={
                      !trusted ||
                      !(authMethod === "key" ? privateKey : password)
                    }
                    onClick={() =>
                      void act(async () => {
                        await api("/updates/seedbox-agent/prepare", "POST", {
                          port,
                          fingerprint,
                          ...(authMethod === "key"
                            ? { private_key: privateKey }
                            : { password }),
                          remember,
                        });
                        setPassword("");
                        setPrivateKey("");
                        await reload();
                      })
                    }
                  >
                    {remember
                      ? t("Verify and save SSH access")
                      : t("Prepare SSH for update")}
                  </button>
                </>
              )}
              {check.credentialsStored && (
                <button
                  disabled={!trusted || !fingerprint}
                  onClick={() =>
                    void act(async () => {
                      await api(
                        "/updates/seedbox-agent/prepare-saved",
                        "POST",
                        { port, fingerprint },
                      );
                      setTrusted(false);
                      fingerprintVerified.current = true;
                      setFingerprintChanged(false);
                      await reload();
                    })
                  }
                >
                  {t("Verify and save new SSH fingerprint")}
                </button>
              )}
            </>
            <p>
              {check.installReady
                ? t("SSH is ready. Use Update Agent or Update all.")
                : t("Prepare SSH to enable installation.")}
            </p>
          </fieldset>
        </details>
      )}
      {operation && <OperationProgress activeOnly operation={operation} />}
    </Panel>
  );
}
