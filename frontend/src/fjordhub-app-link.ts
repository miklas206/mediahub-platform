import { fjordHubLink } from "./fjordhub-token-guide";

// Child links are browser-only: trust the configured LAN host, not arbitrary
// upstream origins. A different explicitly supplied port is allowed.
export function fjordHubAppLink(
  baseUrl: string,
  app: Record<string, string | number>,
  overrides: Record<string, string> = {},
  allowHttp = false,
): { href: string; management: boolean } | null {
  const management = fjordHubLink(baseUrl);
  if (!management || !/^[A-Za-z0-9_-]{1,100}$/.test(String(app.id)))
    return null;
  const base = new URL(management);
  const override = overrides[String(app.id)];
  if (override) {
    try {
      const url = new URL(override);
      if (
        !/[\s\\\u007f]/.test(decodeURIComponent(override)) &&
        (url.protocol === "https:" ||
          (allowHttp && url.protocol === "http:")) &&
        url.hostname === base.hostname &&
        !url.username &&
        !url.password &&
        !url.search &&
        !url.hash &&
        url.port !== "0"
      )
        return { href: url.href, management: false };
    } catch {
      /* Invalid persisted metadata falls back to explicit API links. */
    }
  }
  for (const field of ["url", "local_url", "external_url"]) {
    const value = app[field];
    if (typeof value !== "string" || /[\s\\%]/.test(value)) continue;
    try {
      const url = new URL(value);
      if (
        url.protocol === base.protocol &&
        url.hostname === base.hostname &&
        !url.username &&
        !url.password &&
        !url.search &&
        !url.hash &&
        url.port !== "0" &&
        url.href !== `${base.origin}/`
      )
        return { href: url.href, management: false };
    } catch {
      /* Invalid optional metadata is not an app address. */
    }
  }
  return {
    href: `${management}/#card-${encodeURIComponent(String(app.id))}`,
    management: true,
  };
}
