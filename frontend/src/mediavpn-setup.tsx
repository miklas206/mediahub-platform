import { t } from "./i18n";
import { ExternalLink } from "lucide-react";
import { Panel } from "./phase2";
import "./managed-app-setup.css";
import { ServiceIcon } from "./service-icon";

export function MediaVPNSetupPage() {
  return <div className="stack managed-app-setup">
    <h2 className="managed-app-title"><ServiceIcon packageId="org.mediahub.mediavpn" /> MediaVPN</h2>
    <Panel title={t("Independent VPN app")}>
      <p>{t("MediaVPN manages WireGuard profiles, server selection and port forwarding. MediaSeed only uses MediaVPN when you select it in MediaSeed.")}</p>
      <p>{t("MediaVPN is not installed or connected to this hub yet. The fresh release does not yet support automatic installation of the independent app.")}</p>
      <p>{t("The server administrator must provision MediaVPN and register its HTTPS address for hub login. Open app and connection status will then appear here.")}</p>
      <a className="managed-app-guide" href="https://github.com/miklas206/mediavpn" target="_blank" rel="noreferrer"><ExternalLink size={16} /> {t(" MediaVPN and installation guide")}</a>
    </Panel>
  </div>;
}
