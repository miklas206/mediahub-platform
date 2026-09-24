import { useState, type FormEvent } from "react";
import { Archive, ShieldCheck } from "lucide-react";
import { downloadBackup } from "./api";
import { Panel, ErrorBox, useLoad } from "./phase2";

export function BackupsPage() {
  const [scope, setScope] = useState("core");
  const { data, error } = useLoad<{ includes: string[]; excludes: string[] }>(
    "/backups",
  );
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [failure, setFailure] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setFailure("");
    setMessage("");
    if (values.get("backupPassword") !== values.get("confirmation")) {
      setFailure("Backup passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const blob = await downloadBackup(
        {
          password: values.get("password"),
          code: values.get("code") || "",
          backupPassword: values.get("backupPassword"),
        },
        scope,
      );
      const url = URL.createObjectURL(blob),
        link = document.createElement("a");
      link.href = url;
      link.download = `mediahub-${scope}-${new Date().toISOString().slice(0, 10)}.mhbackup`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      form.reset();
      setMessage(
        "Encrypted configuration backup verified and downloaded. Keep its password separately. Media files are not included.",
      );
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="stack">
      <ErrorBox error={error || failure} />
      <div className="runtime-panels">
        <Panel
          title={`${scope === "core" ? "MediaHub" : scope === "plex" ? "Plex" : "Seedbox"} configuration backup`}
        >
          <Archive />
          <p>
            Export a portable, password-encrypted copy of the selected
            configuration. The server verifies the archive before downloading
            it.
          </p>
          <h3>Included</h3>
          <ul>
            {(scope === "core"
              ? data?.includes || []
              : scope === "plex"
                ? [
                    "Library databases",
                    "Encrypted account preferences",
                    "Installation and storage policy",
                  ]
                : [
                    "Client settings and torrent job metadata",
                    "Encrypted VPN and client credentials",
                    "Installation and recovery configuration",
                  ]
            ).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <h3>Not included</h3>
          <ul>
            {(scope === "core"
              ? data?.excludes || []
              : [
                  "Media and downloaded files",
                  "Artwork caches and diagnostic logs",
                  "TLS certificates and host deployment",
                ]
            ).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p className="muted">
            This is not a full server backup. Keep separate backups of app data,
            deployment certificates and irreplaceable media. Restore is an
            offline maintenance operation.
          </p>
        </Panel>
        <Panel title="Create encrypted backup">
          <ShieldCheck />
          <form className="security-card" onSubmit={submit}>
            <label>
              What to back up
              <select
                value={scope}
                disabled={busy}
                onChange={(e) => setScope(e.target.value)}
              >
                <option value="core">
                  MediaHub · settings, accounts and storage mappings
                </option>
                <option value="plex">
                  Plex · library database and encrypted preferences
                </option>
                <option value="seedbox">
                  Seedbox · client configuration and encrypted secrets
                </option>
              </select>
            </label>
            {scope !== "core" && (
              <p className="notice">
                The selected app pauses briefly for a consistent backup, then
                resumes if it was running. Media, artwork caches and downloaded
                files are excluded. Maximum configuration size: 48 MiB.
              </p>
            )}
            <label>
              Current MediaHub password
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>
            <label>
              Authenticator or recovery code
              <input name="code" autoComplete="one-time-code" maxLength={32} />
            </label>
            <label>
              Backup password
              <input
                name="backupPassword"
                type="password"
                autoComplete="new-password"
                minLength={16}
                maxLength={256}
                required
              />
            </label>
            <label>
              Confirm backup password
              <input
                name="confirmation"
                type="password"
                autoComplete="new-password"
                minLength={16}
                maxLength={256}
                required
              />
            </label>
            <p>
              The backup password is not stored. Without it, the backup cannot
              be recovered.
            </p>
            <button className="primary" disabled={busy || !data}>
              {busy ? "Encrypting and verifying…" : "Download encrypted backup"}
            </button>
          </form>
          <p role="status">{message}</p>
        </Panel>
      </div>
    </div>
  );
}
