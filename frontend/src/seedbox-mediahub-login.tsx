import { useEffect, useState } from "react";
import { api } from "./api";
import { ErrorBox } from "./phase2";
import { t } from "./i18n";

export function SeedboxMediaHubLogin({
  operation,
  revision,
  disabled = false,
  onSaved,
}: {
  operation: "install" | "rotate";
  revision?: number;
  disabled?: boolean;
  onSaved?: () => Promise<void>;
}) {
  const [account, setAccount] = useState<{
    username: string;
    totpEnabled: boolean;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [accepted, setAccepted] = useState(false);
  useEffect(() => {
    let active = true;
    void api<{ username: string; totpEnabled: boolean }>("/auth/me")
      .then((value) => {
        if (active) setAccount(value);
      })
      .catch((error: Error) => {
        if (active) setFailure(error.message);
      });
    return () => {
      active = false;
    };
  }, []);
  return (
    <details>
      <summary>{t("Use my MediaHub login")}</summary>
      <p>
        {t(
          "Copy your current MediaHub username and password to qBittorrent once. Later MediaHub password changes do not update qBittorrent. This stores the copied password encrypted on the Seedbox Agent; using separate credentials is safer.",
        )}
      </p>
      <p>
        {t(
          "The Seedbox policy requires a 16–256 character password without control characters and a username of 1–64 letters, digits, dots, underscores or hyphens. Shorter MediaHub passwords cannot be copied.",
        )}
      </p>
      <ErrorBox error={failure} />
      {account && (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const fields = new FormData(form);
            const password = fields.get("password");
            const secondFactor = fields.get("secondFactor") || "";
            form.reset();
            setBusy(true);
            setAccepted(false);
            setFailure("");
            try {
              const current =
                revision === undefined
                  ? await api<{
                      revision: number;
                      busy: boolean;
                      step: number;
                      transaction: { state: string };
                    }>("/seedbox/wizard")
                  : null;
              if (
                current &&
                (current.busy ||
                  current.step !== 12 ||
                  current.transaction.state === "ManualIntervention")
              ) {
                throw new Error(
                  t(
                    "Seedbox must be installed and idle before copying credentials.",
                  ),
                );
              }
              await api("/seedbox/wizard/client/mediahub", "POST", {
                revision: revision ?? current?.revision,
                operation,
                password,
                secondFactor,
              });
              setAccepted(true);
              await onSaved?.();
            } catch (error) {
              setFailure((error as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            {t("MediaHub username")}{" "}
            <input value={account.username} readOnly autoComplete="username" />
          </label>
          <label>
            {t("Current MediaHub password")}{" "}
            <input
              name="password"
              type="password"
              required
              minLength={16}
              maxLength={256}
              autoComplete="current-password"
              disabled={busy || disabled}
            />
          </label>
          {account.totpEnabled && (
            <label>
              {t("Authenticator or recovery code")}{" "}
              <input
                name="secondFactor"
                required
                maxLength={32}
                autoComplete="one-time-code"
                disabled={busy || disabled}
              />
            </label>
          )}
          <button disabled={busy || disabled}>
            {t(
              operation === "rotate"
                ? "Copy login & rotate qBittorrent credentials"
                : "Copy login for installation",
            )}
          </button>
        </form>
      )}
      {accepted && (
        <p role="status">
          {t(
            operation === "rotate"
              ? "Credential rotation accepted. Check Seedbox installation status for verification or recovery before using the new login."
              : "Encrypted client credentials saved for installation.",
          )}
        </p>
      )}
    </details>
  );
}
