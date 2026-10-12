import { t } from "./i18n";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { ServiceIcon } from "./service-icon";

export function MediaVPNSetupPage() {
  return <div className="stack">
    <Link to="/"><ArrowLeft size={16} /> {t(" Back to apps")}</Link>
    <h1><ServiceIcon packageId="org.mediahub.mediavpn" /> MediaVPN</h1>
    <section className="panel stack">
      <h2>{t("Independent VPN app")}</h2>
      <p>{t("MediaVPN manages WireGuard profiles, server selection and port forwarding. MediaSeed only uses MediaVPN when you select it in MediaSeed.")}</p>
      <p>{t("MediaVPN is not installed or connected to this hub yet. The fresh release does not yet support automatic installation of the independent app.")}</p>
      <p>{t("The server administrator must provision MediaVPN and register its HTTPS address for hub login. Open app and connection status will then appear here.")}</p>
      <a href="https://github.com/miklas206/mediavpn" target="_blank" rel="noreferrer"><ExternalLink size={16} /> {t(" MediaVPN and installation guide")}</a>
    </section>
  </div>;
}
