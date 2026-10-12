import { ArrowLeft, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { ServiceIcon } from "./service-icon";

export function MediaVPNSetupPage() {
  return <div className="stack">
    <Link to="/"><ArrowLeft size={16} /> Tilbage til apps</Link>
    <h1><ServiceIcon packageId="org.mediahub.mediavpn" /> MediaVPN</h1>
    <section className="panel stack">
      <h2>Selvstændig VPN-app</h2>
      <p>MediaVPN styrer WireGuard-profiler, servervalg og port-forwarding. MediaSeed bruger kun MediaVPN, når du selv vælger det i MediaSeed.</p>
      <p>MediaVPN er endnu ikke installeret eller tilsluttet denne hub. Den friske release har endnu ikke automatisk installation af den selvstændige app.</p>
      <p>Serverens administrator skal klargøre MediaVPN og registrere dens HTTPS-adresse til hub-login. Derefter vises Åbn app og forbindelsesstatus her.</p>
      <a href="https://github.com/miklas206/mediavpn" target="_blank" rel="noreferrer"><ExternalLink size={16} /> MediaVPN og installationsvejledning</a>
    </section>
  </div>;
}
