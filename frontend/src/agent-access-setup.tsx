import { useEffect, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { ErrorBox } from "./phase2";

type Access = {
  created: boolean;
  host: string;
  publicKey?: string;
  command?: string;
};

export function AgentAccessSetup({
  disabled,
  onReady,
}: {
  disabled: boolean;
  onReady: () => Promise<void>;
}) {
  const [access, setAccess] = useState<Access>();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [port, setPort] = useState(22);
  const [fingerprint, setFingerprint] = useState("");
  const [installed, setInstalled] = useState(false);
  const [trusted, setTrusted] = useState(false);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let active = true;
    void api<Access>("/updates/seedbox-agent/generated-access").then(
      (value) => {
        if (active) setAccess(value);
      },
      (e) => {
        if (active) setError((e as Error).message);
      },
    );
    return () => {
      active = false;
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
  return (
    <fieldset disabled={disabled || working} className="agent-access-guide">
      <legend>{t("Easy update setup")}</legend>
      <ErrorBox error={error} />
      <p className="muted">
        {t(
          "MediaHub creates and remembers the key for you. You only approve access on your server once.",
        )}
      </p>
      <p>
        <strong>{t("1. Create access")}</strong>
      </p>
      {access?.created ? (
        <p>{t("Your update key is ready and stored encrypted in MediaHub.")}</p>
      ) : (
        <button
          className="primary"
          disabled={!access}
          onClick={() =>
            void act(async () => {
              setAccess(
                await api<Access>(
                  "/updates/seedbox-agent/generated-access",
                  "POST",
                ),
              );
            })
          }
        >
          {t("Create update access")}
        </button>
      )}
      {access?.created && (
        <>
          <p>
            <strong>{t("2. Approve on your server")}</strong>
          </p>
          <p>
            {t(
              "Open the console of the Seedbox server at {host} and log in as root. In Proxmox, select the Seedbox VM and open Console. Paste this command and press Enter.",
              { host: access.host },
            )}
          </p>
          <p className="muted">
            {t(
              "This adds a separate update key. Existing keys, tunnels and files are kept. Run it on the Seedbox server, not on the Proxmox host.",
            )}
          </p>
          <button
            onClick={() =>
              void act(async () => {
                await navigator.clipboard.writeText(access.command!);
                setCopied(true);
              })
            }
          >
            {copied ? t("Command copied") : t("Copy setup command")}
          </button>
          <details>
            <summary>{t("Show setup command")}</summary>
            <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {access.command}
            </pre>
          </details>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={installed}
              onChange={(e) => setInstalled(e.target.checked)}
            />
            {t("I ran the command on my Seedbox server")}
          </label>
          <p>
            <strong>{t("3. Check connection")}</strong>
          </p>
          <details>
            <summary>{t("Different SSH port?")}</summary>
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
          </details>
          <button
            disabled={!installed}
            onClick={() =>
              void act(async () => {
                setFingerprint(
                  (
                    await api<{ fingerprint: string }>(
                      "/updates/seedbox-agent/fingerprint",
                      "POST",
                      { port },
                    )
                  ).fingerprint,
                );
                setTrusted(false);
              })
            }
          >
            {t("Check my server")}
          </button>
          {fingerprint && (
            <>
              <p style={{ overflowWrap: "anywhere" }}>{fingerprint}</p>
              <p className="muted">
                {t(
                  "Compare this code with the SHA256 code printed by the setup command in your server console.",
                )}
              </p>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={trusted}
                  onChange={(e) => setTrusted(e.target.checked)}
                />
                {t("The codes match")}
              </label>
              <button
                className="primary"
                disabled={!trusted}
                onClick={() =>
                  void act(async () => {
                    await api(
                      "/updates/seedbox-agent/prepare-generated",
                      "POST",
                      { port, fingerprint },
                    );
                    await onReady();
                  })
                }
              >
                {t("Verify and finish setup")}
              </button>
            </>
          )}
          <p className="muted">
            {t(
              "Connection failed? Make sure the command ran as root on the correct server. Keep the existing tunnel key. Then try again.",
            )}
          </p>
        </>
      )}
    </fieldset>
  );
}
