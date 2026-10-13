import { ManagedAppInstallPage } from "./managed-app-install";
import { SharedVPNPanel } from "./shared-vpn";
import { useData } from "./use-data";
import { useEffect } from "react";
export function MediaVPNSetupPage() {
  const { data, reload } = useData<{ alreadyRunning: boolean }>(
    "/managed-install/org.mediahub.mediavpn",
  );
  useEffect(() => {
    window.addEventListener("apps-changed", reload);
    return () => window.removeEventListener("apps-changed", reload);
  }, [reload]);
  return (
    <div className="stack">
      <ManagedAppInstallPage kind="mediavpn" />
      {data?.alreadyRunning && <SharedVPNPanel />}
    </div>
  );
}
