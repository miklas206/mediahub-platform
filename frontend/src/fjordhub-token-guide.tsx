import { ExternalLink } from "lucide-react";

export function fjordHubLink(value: string): string | null {
  try {
    const url = new URL(value);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      return null;
    // Open the application only; never forward query strings or token fragments.
    return url.origin;
  } catch {
    return null;
  }
}

export function FjordHubTokenGuide({ baseUrl }: { baseUrl: string }) {
  const link = fjordHubLink(baseUrl);
  return (
    <div className="stack fjordhub-token-guide">
      {link ? (
        <a
          className="primary fjordhub-open-link"
          href={link}
          target="_blank"
          rel="noopener noreferrer"
        >
          <ExternalLink size={18} aria-hidden="true" />
          <span>
            Open FjordHub <small>{link}</small>
          </span>
        </a>
      ) : (
        <p>
          Enter FjordHub’s local IP address and port in the FjordHub URL field
          below. An open button will appear here.
        </p>
      )}
      <ol className="fjordhub-token-steps">
        <li>
          Open FjordHub using the button above and sign in as an administrator.
          Complete administrator setup first if this is a new installation.
        </li>
        <li>
          Click the gear icon in the left sidebar:{" "}
          <strong>Settings (Indstillinger)</strong>.
        </li>
        <li>
          Select the <strong>Access Tokens (Adgangstokens)</strong> tab and
          create a new token.
        </li>
        <li>
          Click <strong>Copy token (Kopiér token)</strong> before leaving that
          screen. The token is only shown once. Then click{" "}
          <strong>Done (Færdig)</strong>.
        </li>
        <li>
          Return to MediaHub and paste it into <strong>Access Token</strong>.
          For an <code>http://</code> LAN address, select{" "}
          <strong>Allow HTTP to this LAN-only FjordHub API</strong>.
        </li>
        <li>
          Click <strong>Test Connection</strong>, then <strong>Save</strong>{" "}
          once the connection succeeds.
        </li>
      </ol>
    </div>
  );
}
