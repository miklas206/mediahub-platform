import { getLocale, translateText, t } from "./i18n";

import { LayoutGroup } from "./page-layout";
import { useEffect, useState, type FormEvent } from "react";
import { ShieldCheck, KeyRound, Monitor, RefreshCw } from "lucide-react";
import { api, setCsrf } from "./api";

type Security = {
  totpEnabled: boolean;
  recoveryCodesRemaining: number;
  requireTotp: boolean;
};
type SessionInfo = {
  id: string;
  createdAt: string;
  expiresAt: number;
  current: boolean;
};

export function SecuritySettings() {
  const [status, setStatus] = useState<Security>();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [qr, setQr] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const reload = () => {
    Promise.all([
      api<Security>("/security"),
      api<SessionInfo[]>("/security/sessions"),
    ])
      .then(([s, list]) => {
        setStatus(s);
        setSessions(list);
      })
      .catch((e) => setError(e.message));
  };
  useEffect(reload, []);
  useEffect(
    () => () => {
      if (qr) URL.revokeObjectURL(qr);
    },
    [qr],
  );
  async function submit(
    event: FormEvent<HTMLFormElement>,
    action:
      "enroll" | "confirm" | "recovery" | "password" | "policy" | "disable",
  ) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (action === "confirm") {
        const data = await api<{ recoveryCodes: string[]; csrf: string }>(
          "/security/totp/confirm",
          "POST",
          { code: fields.get("code") },
        );
        setCsrf(data.csrf);
        setCodes(data.recoveryCodes);
        setQr("");
        reload();
      } else {
        const proof = {
          password: fields.get("password"),
          code: fields.get("code") || "",
        };
        if (action === "enroll") {
          const data = await api<{ qrSvg: string }>(
            "/security/totp/enroll",
            "POST",
            proof,
          );
          setQr(
            URL.createObjectURL(
              new Blob([data.qrSvg], { type: "image/svg+xml" }),
            ),
          );
        } else if (action === "recovery") {
          const data = await api<{ recoveryCodes: string[] }>(
            "/security/totp/recovery-codes",
            "POST",
            proof,
          );
          setCodes(data.recoveryCodes);
          reload();
        } else if (action === "policy") {
          await api("/security/policy", "POST", {
            ...proof,
            requireTotp: fields.get("requireTotp") === "on",
          });
          setNotice("Security policy saved.");
          reload();
        } else if (action === "disable") {
          await api("/security/totp/disable", "POST", proof);
          window.dispatchEvent(new Event("session-expired"));
        } else {
          await api("/security/password", "POST", {
            ...proof,
            newPassword: fields.get("newPassword"),
          });
          window.dispatchEvent(new Event("session-expired"));
        }
      }
      form.reset();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <LayoutGroup id="security-extra-1" className="security-workspace">
      <header>
        <div>
          <span className="eyebrow">{t("ACCOUNT PROTECTION")}</span>
          <h2>
            <ShieldCheck size={22} />
            {t(" Security")}
          </h2>
        </div>
        <button onClick={reload} aria-label={t("Refresh security status")}>
          <RefreshCw size={16} />
        </button>
      </header>
      {error && (
        <div className="notice" role="alert">
          {translateText(error)}
        </div>
      )}
      {notice && <p role="status">{translateText(notice)}</p>}
      {codes.length > 0 && (
        <div className="recovery-panel" role="status">
          <h3>{t("Save your recovery codes")}</h3>
          <p>
            {t(
              "Shown only once. Store them somewhere private, outside MediaHub. Each code works once with your password.",
            )}
          </p>
          <div className="recovery-grid">
            {codes.map((c) => (
              <code key={c}>{c}</code>
            ))}
          </div>
          <button onClick={() => setCodes([])}>
            {t("I have saved these codes")}
          </button>
        </div>
      )}
      <LayoutGroup id="security-SecuritySettings-1" className="security-grid">
        <article className="security-card">
          <ShieldCheck />
          <h3>{t("Authenticator app")}</h3>
          <p>
            {t(
              "Use Google Authenticator, Microsoft Authenticator, Bitwarden or another TOTP app.",
            )}
          </p>
          {!status ? (
            <p role="status">{t("Checking account protection…")}</p>
          ) : qr ? (
            <>
              <img
                className="totp-qr"
                src={qr}
                alt={t("Scan this private setup code with your authenticator")}
              />
              <p>
                {t(
                  "Scan the code, then enter the six digits from your app. Setup expires after ten minutes.",
                )}
              </p>
              <form onSubmit={(e) => submit(e, "confirm")}>
                <label>
                  {t("Authenticator code")}
                  <input
                    name="code"
                    autoComplete="one-time-code"
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    required
                  />
                </label>
                <button className="primary" disabled={busy}>
                  {t("Verify and enable")}
                </button>
                <button type="button" onClick={() => setQr("")}>
                  {t("Cancel")}
                </button>
              </form>
            </>
          ) : status.totpEnabled ? (
            <>
              <span className="badge healthy">{t("Enabled")}</span>
              <p>
                {status.recoveryCodesRemaining}
                {t(" recovery codes remain.")}
              </p>
              <details>
                <summary>{t("Generate new recovery codes")}</summary>
                <p>{t("This replaces all previous recovery codes.")}</p>
                <form onSubmit={(e) => submit(e, "recovery")}>
                  <IdentityFields secondFactor />
                  <button disabled={busy}>{t("Replace recovery codes")}</button>
                </form>
              </details>
            </>
          ) : (
            <form onSubmit={(e) => submit(e, "enroll")}>
              <IdentityFields />
              <button className="primary" disabled={busy}>
                {t("Set up two-factor authentication")}
              </button>
            </form>
          )}
        </article>
        <article className="security-card">
          <KeyRound />
          <h3>{t("Password")}</h3>
          <p>
            {t(
              "Changing your password signs out every session, including this one.",
            )}
          </p>
          <form onSubmit={(e) => submit(e, "password")}>
            <IdentityFields secondFactor={status?.totpEnabled} />
            <label>
              {t("New password")}
              <input
                type="password"
                name="newPassword"
                autoComplete="new-password"
                minLength={12}
                maxLength={256}
                required
              />
            </label>
            <button disabled={busy}>{t("Change password")}</button>
          </form>
        </article>
      </LayoutGroup>
      {status?.totpEnabled && (
        <article className="security-card">
          <ShieldCheck />
          <h3>{t("Security policy")}</h3>
          <form onSubmit={(e) => submit(e, "policy")}>
            <label>
              <input
                type="checkbox"
                name="requireTotp"
                defaultChecked={status.requireTotp}
              />{" "}
              {t("Require an authenticator for access to MediaHub")}
            </label>
            <IdentityFields secondFactor />
            <button disabled={busy}>{t("Save security policy")}</button>
          </form>
          {!status.requireTotp && (
            <details>
              <summary>{t("Disable authenticator")}</summary>
              <p>
                {t(
                  "This signs out all sessions. Sign in with your password to set up a different authenticator.",
                )}
              </p>
              <form onSubmit={(e) => submit(e, "disable")}>
                <IdentityFields secondFactor />
                <label>
                  <input type="checkbox" required />
                  {t(" I understand that password-only access will be enabled")}
                </label>
                <button disabled={busy}>
                  {t("Disable two-factor authentication")}
                </button>
              </form>
            </details>
          )}
        </article>
      )}
      <article className="security-card">
        <Monitor />
        <h3>{t("Signed-in sessions")}</h3>
        {sessions.map((s) => (
          <div className="session-row" key={s.id}>
            <div>
              <strong>
                {s.current ? t("This session") : t("Another session")}
              </strong>
              <p>
                {t("Signed in ")}
                {new Date(s.createdAt).toLocaleString(getLocale())}
                {t(" · Expires")}{" "}
                {new Date(s.expiresAt * 1000).toLocaleString(getLocale())}
              </p>
            </div>
            <button
              disabled={busy}
              onClick={async () => {
                try {
                  await api("/security/sessions/" + s.id, "DELETE");
                  if (s.current)
                    window.dispatchEvent(new Event("session-expired"));
                  else reload();
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              {t("Sign out")}
            </button>
          </div>
        ))}
      </article>
    </LayoutGroup>
  );
}

function IdentityFields({ secondFactor = false }: { secondFactor?: boolean }) {
  return (
    <>
      <label>
        {t("Current password")}
        <input
          name="password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={256}
        />
      </label>
      {secondFactor && (
        <label>
          {t("Authenticator or recovery code")}
          <input
            name="code"
            autoComplete="one-time-code"
            required
            maxLength={32}
          />
        </label>
      )}
    </>
  );
}
