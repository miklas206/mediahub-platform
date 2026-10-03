import { t } from "./i18n";
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
            {t("Open FjordHub ")}
            <small>{link}</small>
          </span>
        </a>
      ) : (
        <p>
          {t(
            "Enter FjordHub’s local IP address and port in the FjordHub URL field below. An open button will appear here.",
          )}
        </p>
      )}
      <ol className="fjordhub-token-steps">
        <li>
          {t(
            "Open FjordHub using the button above and sign in as an administrator. Complete administrator setup first if this is a new installation.",
          )}
        </li>
        <li>
          {t("Click the gear icon in the left sidebar:")}{" "}
          <strong>{t("Settings (Indstillinger)")}</strong>.
        </li>
        <li>
          {t("Select the ")}
          <strong>{t("Access Tokens (Adgangstokens)")}</strong>
          {t(" tab and create a new token.")}
        </li>
        <li>
          {t("Click ")}
          <strong>{t("Copy token (Kopiér token)")}</strong>
          {t(
            " before leaving that screen. The token is only shown once. Then click",
          )}{" "}
          <strong>{t("Done (Færdig)")}</strong>.
        </li>
        <li>
          {t("Return to MediaHub and paste it into ")}
          <strong>{t("Access Token")}</strong>
          {t(". For an ")}
          <code>http://</code>
          {t(" LAN address, select")}{" "}
          <strong>{t("Allow HTTP to this LAN-only FjordHub API")}</strong>.
        </li>
        <li>
          {t("Click ")}
          <strong>{t("Test Connection")}</strong>
          {t(", then ")}
          <strong>{t("Save")}</strong> {t("once the connection succeeds.")}
        </li>
      </ol>
    </div>
  );
}
