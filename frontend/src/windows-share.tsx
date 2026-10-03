import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Clipboard,
  Download,
  FolderOpen,
  HardDrive,
  Info,
  KeyRound,
  Laptop,
  Network,
  RefreshCw,
  Server,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { api } from "./api";
import { getLocale, t, translateText } from "./i18n";
import { LayoutGroup } from "./page-layout";
import "./windows-share.css";

type ShareConfiguration = {
  server: string;
  shareName: string;
  username: string;
  driveLetter: string;
};
type ConfigurationResponse = {
  configured: boolean;
  appId: string | null;
  configuration: ShareConfiguration | null;
};
type ShareStatus = {
  configured: boolean;
  status: "not_configured" | "reachable" | "unreachable";
  checkedAt: string | null;
  checkedFrom: "mediahub-core";
  server: string | null;
  port: 445;
  tcpReachable: boolean | null;
  latencyMs: number | null;
  shareAccessVerified: false;
  windowsAccessVerified: false;
  message: string;
  cached?: boolean;
};
const defaults: ShareConfiguration = {
  server: "",
  shareName: "MediaHub",
  username: "",
  driveLetter: "M",
};
const letters = "DEFGHIJKLMNOPQRSTUVWXYZ".split("");
const uncPath = (configuration: ShareConfiguration) =>
  `\\\\${configuration.server}\\${configuration.shareName}`;

export function WindowsSharePage({
  onConfigured,
}: { onConfigured?: () => void } = {}) {
  const [saved, setSaved] = useState<ConfigurationResponse>();
  const [form, setForm] = useState<ShareConfiguration>(defaults);
  const [status, setStatus] = useState<ShareStatus>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<
    "save" | "check" | "connect" | "diagnostics" | "reset-password" | null
  >(null);
  const [error, setError] = useState("");
  const [checkError, setCheckError] = useState("");
  const [message, setMessage] = useState("");
  const [step, setStep] = useState(1);
  const [revision, setRevision] = useState(0);
  const configuration = saved?.configured ? saved.configuration : null;
  const path = configuration ? uncPath(configuration) : "";
  const dirty =
    configuration &&
    Object.keys(defaults).some(
      (key) =>
        form[key as keyof ShareConfiguration] !==
        configuration[key as keyof ShareConfiguration],
    );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void Promise.allSettled([
      api<ConfigurationResponse>(
        "/windows-share/configuration",
        "GET",
        undefined,
        controller.signal,
      ),
      api<ShareStatus>(
        "/windows-share/status",
        "GET",
        undefined,
        controller.signal,
      ),
    ]).then(([config, check]) => {
      if (controller.signal.aborted) return;
      if (config.status === "fulfilled") {
        setSaved(config.value);
        setForm(config.value.configuration || defaults);
        setStep(config.value.configured ? 2 : 1);
      } else setError((config.reason as Error).message);
      if (check.status === "fulfilled") setStatus(check.value);
      else setCheckError((check.reason as Error).message);
      setLoading(false);
    });
    return () => controller.abort();
  }, [revision]);

  function goTo(next: number) {
    setStep(next);
    const target = document.getElementById(`windows-share-step-${next}`);
    target?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "start",
    });
    target?.focus({ preventScroll: true });
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || loading || !saved) return;
    const octets = form.server.trim().split(".");
    const numbers = octets.map(Number);
    if (
      octets.length !== 4 ||
      octets.some((octet) => !/^(0|[1-9][0-9]{0,2})$/.test(octet)) ||
      numbers.some((number) => number > 255) ||
      !(
        numbers[0] === 10 ||
        (numbers[0] === 172 && numbers[1] >= 16 && numbers[1] <= 31) ||
        (numbers[0] === 192 && numbers[1] === 168)
      )
    ) {
      setError(
        "Enter the SMB server's private IPv4 address, such as 192.168.1.10.",
      );
      return;
    }
    const shareName = form.shareName.trim();
    const username = form.username.trim();
    if (
      !/^[\p{L}\p{N} ._$-]+$/u.test(shareName) ||
      shareName === "." ||
      shareName === ".." ||
      shareName.endsWith(".")
    ) {
      setError(
        "Enter the published share name without a folder path or special command characters.",
      );
      return;
    }
    if (username && !/^[\p{L}\p{N} ._@\\-]+$/u.test(username)) {
      setError("Enter an SMB username without special command characters.");
      return;
    }
    setBusy("save");
    setError("");
    setMessage("");
    try {
      const result = await api<ConfigurationResponse>(
        "/windows-share/configuration",
        "PUT",
        {
          server: form.server.trim(),
          shareName,
          username,
          driveLetter: form.driveLetter,
        },
      );
      setSaved(result);
      setForm(result.configuration || defaults);
      setStatus(undefined);
      setCheckError("");
      setMessage("Share details saved. Continue on your Windows PC.");
      window.dispatchEvent(new Event("apps-changed"));
      onConfigured?.();
      requestAnimationFrame(() => goTo(2));
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function copyPath() {
    setMessage("");
    try {
      await navigator.clipboard.writeText(path);
      setMessage("Network path copied.");
    } catch {
      setMessage("Select the network path and copy it manually.");
    }
  }

  async function download(kind: "connect" | "diagnostics" | "reset-password") {
    if (!configuration || busy) return;
    setBusy(kind);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`/api/v1/windows-share/${kind}.ps1`, {
        credentials: "same-origin",
      });
      if (!response.ok) {
        let detail = "The Windows helper could not be downloaded. Try again.";
        try {
          const result = await response.json();
          detail = result.error?.message || detail;
        } catch {
          /* A proxy may return HTML. */
        }
        throw new Error(detail);
      }
      if (
        /text\/html|application\/json/i.test(
          response.headers.get("content-type") || "",
        )
      ) {
        throw new Error(
          "The Windows helper could not be downloaded. Try again.",
        );
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${kind}.ps1`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(
        kind === "reset-password"
          ? "Password reset helper downloaded. Run it on Windows with your Samba server administrator login."
          : kind === "connect"
            ? "Connection helper downloaded. Run it on your Windows PC."
            : "Diagnostic helper downloaded. Its results appear on your Windows PC.",
      );
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function check() {
    if (!configuration || busy) return;
    setBusy("check");
    setCheckError("");
    try {
      setStatus(await api<ShareStatus>("/windows-share/check", "POST", {}));
    } catch (failure) {
      setCheckError((failure as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const time =
    status?.checkedAt && Number.isFinite(Date.parse(status.checkedAt))
      ? new Date(status.checkedAt).toLocaleString(getLocale())
      : null;

  return (
    <div className="windows-share-page">
      <div className="windows-share-intro" data-layout-fixed>
        <span className="windows-share-app-icon">
          <Laptop size={24} />
        </span>
        <div>
          <p>
            {t(
              "Open your existing media folders directly in Windows File Explorer.",
            )}
          </p>
          <small>
            {t("Local network access · Your files stay on your server")}
          </small>
        </div>
        <span className={`badge ${configuration ? "available" : "unknown"}`}>
          <span aria-hidden="true" />
          {t(
            loading
              ? "Loading connection…"
              : !saved
                ? "Connection unavailable"
                : configuration
                  ? "Details saved"
                  : "Not configured",
          )}
        </span>
      </div>
      <nav
        className="windows-share-steps"
        aria-label={t("Windows connection setup")}
      >
        {[
          [1, t("Share details")],
          [2, t("Connect Windows")],
          [3, t("Check connection")],
        ].map(([number, label]) => (
          <button
            key={number}
            type="button"
            aria-current={step === number ? "step" : undefined}
            disabled={number !== 1 && !configuration}
            onClick={() => goTo(Number(number))}
          >
            <span>
              {number === 1 && configuration ? <Check size={14} /> : number}
            </span>
            {label}
            <ChevronRight size={14} />
          </button>
        ))}
      </nav>
      {message && (
        <p className="windows-share-feedback" role="status">
          {translateText(message)}
        </p>
      )}
      {error && (
        <div className="notice windows-share-feedback" role="alert">
          {translateText(error)}
          {!saved && !loading && (
            <button
              type="button"
              onClick={() => setRevision((value) => value + 1)}
            >
              <RefreshCw size={14} />
              {t("Try again")}
            </button>
          )}
        </div>
      )}
      <LayoutGroup id="windows-share-panels" className="windows-share-grid">
        <section
          className="panel windows-share-card"
          key="details"
          data-layout-title={t("Share details")}
        >
          <header className="panel-heading">
            <h2 id="windows-share-step-1" tabIndex={-1}>
              <Server size={18} />
              {t("1. Share details")}
            </h2>
          </header>
          <div className="windows-share-content">
            <p className="muted">
              {t(
                "Register an existing SMB share from your NAS or Samba server. This guide does not create the server share.",
              )}
            </p>
            <details className="windows-share-help">
              <summary>{t("Before you begin")}</summary>
              <ul>
                <li>
                  {t(
                    "Create or choose a share on your NAS or Samba server using SMB 2 or SMB 3.",
                  )}
                </li>
                <li>
                  {t(
                    "Give a dedicated user access to the share and its media folders, including write permission if you want to upload files.",
                  )}
                </li>
                <li>
                  {t(
                    "Allow SMB on TCP port 445 within your local network. Keep the server's private IP address stable.",
                  )}
                </li>
                <li>
                  {t(
                    "You will enter the share password in Windows. MediaHub does not store it.",
                  )}
                </li>
              </ul>
              <a
                className="text-link"
                href="https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html"
                target="_blank"
                rel="noreferrer"
              >
                {t("Samba's share configuration reference")}
                <ChevronRight size={13} />
              </a>
            </details>
            <form
              className="windows-share-form"
              onSubmit={(event) => void save(event)}
            >
              <fieldset disabled={loading || !saved || !!busy}>
                <label>
                  {t("Server private IPv4 address")}
                  <input
                    required
                    maxLength={15}
                    inputMode="decimal"
                    placeholder="192.168.1.10"
                    pattern="[0-9]{1,3}(\.[0-9]{1,3}){3}"
                    value={form.server}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        server: event.target.value,
                      }))
                    }
                  />
                  <small>
                    {t(
                      "Use the LAN address of the SMB server, not the MediaHub website address.",
                    )}
                  </small>
                </label>
                <label>
                  {t("Share name")}
                  <input
                    required
                    maxLength={80}
                    placeholder="MediaHub"
                    value={form.shareName}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        shareName: event.target.value,
                      }))
                    }
                  />
                  <small>
                    {t(
                      "Enter the published share name, not a Linux folder path.",
                    )}
                  </small>
                </label>
                <label>
                  {t("Windows drive letter")}
                  <select
                    value={form.driveLetter}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        driveLetter: event.target.value,
                      }))
                    }
                  >
                    {letters.map((letter) => (
                      <option key={letter} value={letter}>
                        {letter}:
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {t("SMB username (optional)")}
                  <input
                    autoComplete="off"
                    maxLength={128}
                    placeholder={t("Ask in Windows")}
                    value={form.username}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        username: event.target.value,
                      }))
                    }
                  />
                </label>
              </fieldset>
              <div className="button-row">
                <button
                  type="submit"
                  className="primary"
                  disabled={loading || !saved || !!busy}
                >
                  {busy === "save" ? (
                    <RefreshCw size={15} />
                  ) : (
                    <Check size={15} />
                  )}
                  {t(
                    busy === "save"
                      ? "Saving…"
                      : configuration
                        ? "Save share details"
                        : "Save and continue",
                  )}
                </button>
                {configuration && (
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => goTo(2)}
                  >
                    {t("Connect Windows")}
                    <ArrowRight size={14} />
                  </button>
                )}
              </div>
              {loading && (
                <p className="muted" role="status">
                  {t("Loading share details…")}
                </p>
              )}
            </form>
          </div>
        </section>

        <section
          className="panel windows-share-card"
          key="connect"
          data-layout-title={t("Connect Windows")}
        >
          <header className="panel-heading">
            <h2 id="windows-share-step-2" tabIndex={-1}>
              <FolderOpen size={18} />
              {t("2. Connect this Windows PC")}
            </h2>
          </header>
          <div className="windows-share-content">
            {configuration ? (
              <>
                {dirty && (
                  <p className="windows-share-hint">
                    <Info size={15} />
                    {t(
                      "The connection steps use your saved details. Save your changes before downloading a new helper.",
                    )}
                  </p>
                )}
                <label className="windows-share-path">
                  <span>{t("Saved network path")}</span>
                  <div>
                    <input
                      readOnly
                      value={path}
                      onFocus={(event) => event.target.select()}
                    />
                    <button
                      type="button"
                      onClick={() => void copyPath()}
                      aria-label={t("Copy network path")}
                    >
                      <Clipboard size={16} />
                    </button>
                  </div>
                </label>
                <div className="windows-share-target">
                  <HardDrive size={18} />
                  <span>
                    {t("Map as drive {letter}:", {
                      letter: configuration.driveLetter,
                    })}
                  </span>
                  {configuration.username && (
                    <small>{configuration.username}</small>
                  )}
                </div>
                <div className="windows-share-manual">
                  <h3>{t("Connect in File Explorer")}</h3>
                  <ol>
                    <li>
                      {t(
                        "Open File Explorer with Windows + E. Select This PC, open the More (...) menu and choose Map network drive. You can also right-click This PC.",
                      )}
                    </li>
                    <li>
                      {t(
                        "Choose drive {letter}: and paste the saved network path into Folder.",
                        { letter: configuration.driveLetter },
                      )}
                    </li>
                    <li>
                      {t(
                        "Select Reconnect at sign-in. Choose Connect using different credentials if your share uses another account.",
                      )}
                    </li>
                    <li>
                      {t(
                        "Finish and enter the SMB account and password when Windows asks.",
                      )}
                    </li>
                  </ol>
                  <a
                    className="text-link"
                    href="https://support.microsoft.com/en-us/windows/experience/connectivity-networking/file-sharing-over-a-network-in-windows"
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("Microsoft's Windows file-sharing guide")}
                    <ChevronRight size={13} />
                  </a>
                </div>
                <details className="windows-share-help windows-share-script">
                  <summary>
                    {t("Optional: use the Windows connection helper")}
                  </summary>
                  <p>
                    {t(
                      "Review the downloaded script. It asks for your share password locally and confirms before mapping the drive.",
                    )}
                  </p>
                  <button
                    type="button"
                    className="windows-share-download"
                    disabled={!!busy || !!dirty}
                    onClick={() => void download("connect")}
                  >
                    <Download size={16} />
                    {t(
                      busy === "connect"
                        ? "Downloading…"
                        : "Download Windows connection helper",
                    )}
                  </button>
                  <p>
                    {t(
                      "Save connect.ps1 in Downloads. Open Windows PowerShell as your usual user, without Run as administrator, then run:",
                    )}
                  </p>
                  <code className="windows-share-command">
                    {
                      'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\\Downloads\\connect.ps1"'
                    }
                  </code>
                  <p>
                    {t(
                      "Review the downloaded script before running it. This command allows it only in the new PowerShell process and does not change your permanent script policy. If you saved the file elsewhere, replace the path.",
                    )}
                  </p>
                  <p className="muted">
                    {t(
                      "Enter your SMB username and password in the PowerShell window. These belong to the share on your NAS or Samba server, not necessarily your Windows or MediaHub account. If you forgot the password, cancel and reset it on the file server. MediaHub cannot retrieve it.",
                    )}
                  </p>
                  <p className="windows-share-hint">
                    <ShieldCheck size={15} />
                    {t(
                      "Existing drive mappings are preserved. Windows remembers the new mapping; reconnecting needs the server and valid credentials, and Windows may ask for the password again.",
                    )}
                  </p>
                </details>
                <button
                  type="button"
                  className="windows-share-next"
                  onClick={() => goTo(3)}
                >
                  {t("Next: check the connection")}
                  <ArrowRight size={15} />
                </button>
              </>
            ) : (
              <div className="windows-share-waiting">
                <FolderOpen size={30} />
                <p>
                  {t(
                    "Save the share details first to get your network path and Windows helper.",
                  )}
                </p>
              </div>
            )}
          </div>
        </section>

        <section
          className="panel windows-share-card"
          key="check"
          data-layout-title={t("Check connection")}
        >
          <header className="panel-heading">
            <h2 id="windows-share-step-3" tabIndex={-1}>
              <Network size={18} />
              {t("3. Check the connection")}
            </h2>
          </header>
          <div className="windows-share-content">
            <div className="windows-share-check-heading">
              <Server size={18} />
              <div>
                <strong>{t("Test from MediaHub Core")}</strong>
                <small>{t("Server reachability only")}</small>
              </div>
              <span
                className={`badge ${status?.tcpReachable === true ? "available" : status?.tcpReachable === false ? "degraded" : "unknown"}`}
              >
                {t(
                  status?.tcpReachable === true
                    ? "Port reachable"
                    : status?.tcpReachable === false
                      ? "Port unavailable"
                      : "Not checked",
                )}
              </span>
            </div>
            <p className="muted">
              {t(
                "This checks TCP port 445 from Core. It does not verify the share, your Windows connection, credentials or file permissions.",
              )}
            </p>
            {status?.configured && (
              <dl className="windows-share-check-facts">
                <div>
                  <dt>{t("Server")}</dt>
                  <dd>{status.server}:445</dd>
                </div>
                <div>
                  <dt>{t("Response time")}</dt>
                  <dd>
                    {status.latencyMs == null
                      ? "—"
                      : t("{value} ms", {
                          value: status.latencyMs.toLocaleString(getLocale(), {
                            maximumFractionDigits: 1,
                          }),
                        })}
                  </dd>
                </div>
              </dl>
            )}
            {status?.message && (
              <p className="windows-share-small">
                {translateText(status.message)}
              </p>
            )}
            {time && (
              <p className="windows-share-small">
                {t("Checked: {time}", { time })}
                {status?.cached && ` · ${t("Cached result")}`}
              </p>
            )}
            {checkError && (
              <p className="notice" role="alert">
                {translateText(checkError)}
              </p>
            )}
            <button
              type="button"
              disabled={!configuration || !!busy}
              onClick={() => void check()}
            >
              <RefreshCw size={15} />
              {t(busy === "check" ? "Checking from Core…" : "Check from Core")}
            </button>
            <div className="windows-share-local-check">
              <div className="windows-share-check-heading">
                <Laptop size={18} />
                <div>
                  <strong>{t("Test on your Windows PC")}</strong>
                  <small>
                    {t("Run locally to check the actual connection")}
                  </small>
                </div>
              </div>
              <p className="muted">
                {t(
                  "The read-only diagnostic helper checks the port, existing drive mappings, account conflicts, folder access and the free space reported by your server.",
                )}
              </p>
              <button
                type="button"
                disabled={!configuration || !!busy || !!dirty}
                onClick={() => void download("diagnostics")}
              >
                <Download size={15} />
                {t(
                  busy === "diagnostics"
                    ? "Downloading…"
                    : "Download Windows diagnostic helper",
                )}
              </button>
              <p className="windows-share-small">
                {t(
                  "Run diagnostics.ps1 in PowerShell as the same Windows user who uses File Explorer. Results stay on your PC; the test does not prove write access.",
                )}
              </p>
              <details className="windows-share-help windows-share-script">
                <summary>
                  {t("How to run the Windows diagnostic helper")}
                </summary>
                <p>
                  {t(
                    "Save diagnostics.ps1 in Downloads, review it, and open Windows PowerShell as your usual user. Run:",
                  )}
                </p>
                <code className="windows-share-command">
                  {
                    'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\\Downloads\\diagnostics.ps1"'
                  }
                </code>
                <p>
                  {t(
                    "Run this in ordinary Windows PowerShell, not as administrator, so the check sees the same drives and credentials as File Explorer. The script policy applies only to the new process; your permanent settings are unchanged.",
                  )}
                </p>
              </details>
            </div>
          </div>
        </section>

        <section
          className="panel windows-share-card"
          key="help"
          data-layout-title={t("Connection help")}
        >
          <header className="panel-heading">
            <h2>
              <TriangleAlert size={18} />
              {t("Connection help")}
            </h2>
          </header>
          <div className="windows-share-content windows-share-troubleshooting">
            <details>
              <summary>
                {t(
                  "PowerShell blocks the script or reports PSSecurityException",
                )}
              </summary>
              <p>
                {t(
                  "Use the start command shown in the connection or diagnostics guide. It allows the reviewed script for that process only. Do not change CurrentUser or LocalMachine policy to run these helpers.",
                )}
              </p>
              <p>
                {t(
                  "If the script is still blocked, run Get-ExecutionPolicy -List. MachinePolicy and UserPolicy can be set by an administrator and take precedence. Use the File Explorer steps or contact that administrator instead of changing managed policies.",
                )}
              </p>
              <code className="windows-share-command">
                Get-ExecutionPolicy -List
              </code>
            </details>
            <details>
              <summary>
                {t("The drive is disconnected or Windows reports error 53")}
              </summary>
              <p>
                {t(
                  "Check that Windows and the SMB server are on the same local network, that the server is running, and that the saved private IP address is correct. Run the Windows diagnostic helper to test port 445 from the affected PC.",
                )}
              </p>
              <p>
                {t(
                  "If Core can reach port 445 but Windows cannot, check the PC's network, firewall and VPN route. If both tests fail, check the SMB server and its local firewall.",
                )}
              </p>
            </details>
            <details>
              <summary>
                {t(
                  "Windows reports error 67: the network name cannot be found",
                )}
              </summary>
              <p>
                {t(
                  "Check the published share name in the NAS or Samba configuration. A reachable server port does not prove that this share exists. Use the share name, not a folder path or website URL.",
                )}
              </p>
            </details>
            <details>
              <summary>
                {t("Windows asks for credentials again or reports error 1219")}
              </summary>
              <p>
                {t(
                  "Windows may already be connected to this server using another account. Close open files, inspect existing connections, and disconnect only the affected server's mappings before reconnecting with one SMB account.",
                )}
              </p>
              <p>
                {t(
                  "Check Windows Credential Manager for an outdated saved account for this server. Enter the NAS or Samba account, which may differ from your MediaHub login.",
                )}
              </p>
            </details>
            <details>
              <summary>
                {t("The chosen drive letter is already in use")}
              </summary>
              <p>
                {t(
                  "Choose an unused drive letter, save the details, and download the helper again. The helper keeps any existing or remembered mapping instead of replacing it.",
                )}
              </p>
            </details>
            <details>
              <summary>
                {t("Access is denied (error 5), or files cannot be copied")}
              </summary>
              <p>
                {t(
                  "Folder access does not prove write permission. Check both the SMB share permissions and the underlying folder permissions for your dedicated user, along with available space or a user quota.",
                )}
              </p>
            </details>
            <details>
              <summary>
                {t("Windows shows the wrong amount of free space")}
              </summary>
              <p>
                {t(
                  "Windows displays the capacity reported by the SMB server. Compare it with MediaHub storage, then check NAS quotas or whether Samba reports the correct media filesystem instead of its system disk.",
                )}
              </p>
              <Link className="text-link" to="/storage">
                {t("View storage")}
                <ArrowRight size={13} />
              </Link>
            </details>
            <details>
              <summary>
                {t(
                  "Access from outside your home network or while using a VPN",
                )}
              </summary>
              <p>
                {t(
                  "This guide uses a private LAN address. From another network, connect your Windows PC to your home network through a private VPN before opening the share.",
                )}
              </p>
              <p>
                {t(
                  "The torrent provider VPN does not connect your Windows PC to your home network. A public MediaHub website or HTTPS tunnel is not an SMB network share.",
                )}
              </p>
            </details>
            <p className="windows-share-hint">
              <CheckCircle2 size={16} />
              {t(
                "Saving this guide changes connection details only. Files remain on your server.",
              )}
            </p>
          </div>
        </section>
        <section
          className="panel windows-share-card"
          key="password"
          data-layout-title={t("Reset SMB password")}
        >
          <header className="panel-heading">
            <h2>
              <KeyRound size={18} /> {t("Reset SMB password")}
            </h2>
          </header>
          <div className="windows-share-content">
            <p>
              {t(
                "Forgot the share password? Set a new password for an existing local Samba account. You do not need the old SMB password.",
              )}
            </p>
            <p className="muted">
              {t(
                "Requires a Linux/Samba server with SSH and a server administrator login with sudo or root access. For a NAS or Windows server, reset the account in that server's administration.",
              )}
            </p>
            <button
              type="button"
              className="windows-share-download"
              disabled={!configuration || !!busy || !!dirty}
              onClick={() => void download("reset-password")}
            >
              <Download size={16} />{" "}
              {t(
                busy === "reset-password"
                  ? "Downloading…"
                  : "Download SMB password reset tool",
              )}
            </button>
            {!configuration && (
              <p className="muted">
                {t(
                  "Save the share details first to get your network path and Windows helper.",
                )}
              </p>
            )}
            {dirty && (
              <p className="muted">
                {t(
                  "The connection steps use your saved details. Save your changes before downloading a new helper.",
                )}
              </p>
            )}
            <details className="windows-share-help windows-share-script">
              <summary>
                {t("How to reset the password and reconnect Windows")}
              </summary>
              <ol>
                <li>
                  {t(
                    "Save reset-password.ps1 in Downloads. Open Windows PowerShell as your usual Windows user and run the command below.",
                  )}
                </li>
                <li>
                  {t(
                    "Enter the existing local SMB account and the server's SSH administrator account. Confirm the selected server and account. Verify the SSH fingerprint before accepting a first connection.",
                  )}
                </li>
                <li>
                  {t(
                    "Log in to SSH and sudo when asked. At New SMB password, enter your new share password twice. Passwords stay in the encrypted SSH session and are not sent to MediaHub.",
                  )}
                </li>
                <li>
                  {t(
                    "After the server confirms success, close files on the mapped drive and disconnect only that drive in File Explorer. In Windows Credential Manager, remove an outdated Windows credential for this server if present.",
                  )}
                </li>
                <li>
                  {t(
                    "Reconnect using the saved network path, the SMB account and your new password. Other devices may also need the new password at their next login.",
                  )}
                </li>
              </ol>
              <code className="windows-share-command">
                {
                  'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\\Downloads\\reset-password.ps1"'
                }
              </code>
              <p className="muted">
                {t(
                  "Review the downloaded script before running it. This command allows it only in the new PowerShell process and does not change your permanent script policy. If you saved the file elsewhere, replace the path.",
                )}
              </p>
              <p className="muted">
                {t(
                  "The tool does not create accounts or change shares, folder permissions or media files. It stops if Samba is configured to synchronize Linux passwords. If the administrator login is also forgotten, use the server's recovery procedure.",
                )}
              </p>
            </details>
            <details className="windows-share-help windows-share-script">
              <summary>
                {t("SSH reports Permission denied (publickey)")}
              </summary>
              <p>
                {t(
                  "The server requires an authorized SSH key. An SMB password or MediaHub login cannot replace that key. Run the helper with -IdentityFile and the path to your existing private SSH key; the key stays on your PC.",
                )}
              </p>
              <code className="windows-share-command">
                {
                  'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\\Downloads\\reset-password.ps1" -IdentityFile "$env:USERPROFILE\\.ssh\\id_ed25519"'
                }
              </code>
              <p>
                {t(
                  "Use your actual key path. If you have no authorized key, open the Samba server's console, such as its VM console in Proxmox, and log in as a server administrator. In that server console, list the existing SMB users and reset the correct one:",
                )}
              </p>
              <code className="windows-share-command">
                {"sudo pdbedit -L\nsudo smbpasswd SMB_USER"}
              </code>
              <p>
                {t(
                  "Replace SMB_USER with an existing name from the list, not your Windows display name. A root session can omit sudo. Run these commands inside the Samba server, not on the Proxmox host. You do not need to enable SSH password authentication.",
                )}
              </p>
            </details>
          </div>
        </section>
      </LayoutGroup>
    </div>
  );
}
