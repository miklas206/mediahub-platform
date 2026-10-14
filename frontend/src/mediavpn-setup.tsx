import { ManagedAppInstallPage } from "./managed-app-install";
import { useData } from "./use-data";
import { useEffect } from "react";
import { Panel } from "./phase2";
import { t } from "./i18n";
import { SharedVPNPanel } from "./shared-vpn";
export function MediaVPNSetupPage() {
  const { data, reload } = useData<{ alreadyRunning: boolean }>(
    "/managed-install/org.mediahub.mediavpn",
  );
  const { data: connection } = useData<{
    configured?: boolean;
    url?: string;
    openUrl?: string;
  }>("/mediavpn/status");
  const address = connection?.openUrl || connection?.url;
  useEffect(() => {
    window.addEventListener("apps-changed", reload);
    return () => window.removeEventListener("apps-changed", reload);
  }, [reload]);
  return (
    <div className="stack">
      <ManagedAppInstallPage kind="mediavpn" />
      {(connection?.configured || data?.alreadyRunning) && (
        <SharedVPNPanel appsOnly />
      )}
      {data?.alreadyRunning && (
        <Panel title={t("Shared VPN gateway")}>
          <p>{t("Gateway setup is available inside MediaVPN.")}</p>
          <p className="muted">
            {t(
              "Open MediaVPN, upload a Proton profile and follow the guide for Cloudflare and installed app domains.",
            )}
          </p>
          {address && /^https?:\/\//.test(address) && (
            <a
              className="button primary"
              href={address}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("Open gateway guide")}
            </a>
          )}
          <p className="muted">
            {t(
              "Existing Cloudflare tunnels remain available during migration. Their records are not deleted by this update.",
            )}
          </p>
        </Panel>
      )}
    </div>
  );
}
