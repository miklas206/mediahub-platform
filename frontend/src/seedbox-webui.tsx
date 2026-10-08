import { Panel } from "./phase2";
import { t } from "./i18n";
import { SeedboxMediaHubLogin } from "./seedbox-mediahub-login";

export function seedboxWebUIUrl(value?: string | null): string | null {
  if (
    !value ||
    value.trim() !== value ||
    Array.from(value).some((character) => {
      const code = character.charCodeAt(0);
      return code <= 32 || code === 127;
    })
  )
    return null;
  try {
    const url = new URL(value);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      return null;
    return url.href;
  } catch {
    return null;
  }
}

export function SeedboxWebUI({ operatorUrl }: { operatorUrl?: string | null }) {
  const url = seedboxWebUIUrl(operatorUrl);
  return (
    <Panel title={t("qBittorrent WebUI")}>
      <p>
        {t(
          "Advanced qBittorrent settings use a separate WebUI login. MediaHub does not expose the WebUI or create a connection automatically.",
        )}
      </p>
      <div className="runtime-toolbar">
        {url ? (
          <a
            className="runtime-primary-link"
            href={url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("Open qBittorrent WebUI")}
          </a>
        ) : (
          <button disabled>{t("Open qBittorrent WebUI")}</button>
        )}
      </div>
      <p role="status">
        {url
          ? t(
              "A link is configured, not connection-tested. For localhost access, first start your authorized SSH tunnel on this device and keep it running.",
            )
          : t(
              "WebUI access is not configured. An operator must set MEDIAHUB_OPERATOR_APP_URLS with a seedbox URL after setting up an authorized SSH tunnel or an existing authenticated HTTPS endpoint.",
            )}
      </p>
      <p className="muted">
        {t(
          "The reviewed installation binds the WebUI only to the Seedbox host's loopback address. Use its reviewed WebUI port, not the Agent port. Never disable qBittorrent authentication, CSRF protection or host validation.",
        )}
      </p>
      <SeedboxMediaHubLogin operation="rotate" />
    </Panel>
  );
}
