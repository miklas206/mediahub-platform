import { useState } from "react";
import { t, translateText } from "./i18n";

export type AppRouting = {
  apps?: { packageId: string; name: string }[];
  tunnels?: { id: string; name: string }[];
  routes?: {
    id: string;
    hostname: string;
    packageId: string;
    status: string;
    message: string;
    autoSync: boolean;
  }[];
  connectors?: Record<string, { state?: string }>;
};

export function CloudflareAppRoutes({
  data,
  zones,
  discovered,
  busy,
  change,
}: {
  data: AppRouting;
  zones: { id: string; name: string }[];
  discovered: { id: string; name: string; remote: boolean }[];
  busy: boolean;
  change: (
    path: string,
    method: "POST" | "PUT" | "DELETE",
    body: unknown,
    success: string,
  ) => Promise<void>;
}) {
  const [tunnel, setTunnel] = useState("");
  const [zone, setZone] = useState("");
  const [app, setApp] = useState("");
  const [label, setLabel] = useState("");
  const [name, setName] = useState("MediaHub");
  const selectedTunnel =
    data.tunnels?.find((row) => row.id === tunnel) || data.tunnels?.[0];
  const selectedZone = zones.find((row) => row.id === zone) || zones[0];
  const selectedApp =
    data.apps?.find((row) => row.packageId === app) || data.apps?.[0];
  return (
    <section className="stack">
      <h3>{t("App domains")}</h3>
      <p className="muted">
        {t(
          "Choose an installed app. MediaHub creates its DNS record and tunnel route, and saves the HTTPS address for opening the app and SSO. VPN is optional for this connection.",
        )}
      </p>
      <p className="muted">
        {t(
          "App domains require Zone DNS Edit and Account Cloudflare Tunnel Edit. A connector must be running and trust the app's local certificate.",
        )}
      </p>
      <details>
        <summary>{t("Create or connect a tunnel")}</summary>
        <form
          className="cloudflare-management-form"
          onSubmit={(e) => {
            e.preventDefault();
            void change(
              "/tunnels",
              "POST",
              { name },
              "Tunnel created. Install its connector before opening an app domain.",
            );
          }}
        >
          <label>
            {t("Tunnel name")}
            <input
              required
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <button disabled={busy}>{t("Create tunnel")}</button>
        </form>
        {discovered
          .filter(
            (row) =>
              row.remote && !data.tunnels?.some((saved) => saved.id === row.id),
          )
          .map((row) => (
            <div className="runtime-toolbar" key={row.id}>
              <strong>{row.name}</strong>
              <button
                disabled={busy}
                onClick={() =>
                  void change(
                    "/tunnels/" + row.id + "/adopt",
                    "POST",
                    {},
                    "Tunnel connected. Existing routes were preserved.",
                  )
                }
              >
                {t("Connect tunnel")}
              </button>
            </div>
          ))}
      </details>
      <form
        className="cloudflare-management-form"
        onSubmit={(e) => {
          e.preventDefault();
          void change(
            "/routes",
            "POST",
            {
              tunnelId: selectedTunnel?.id,
              zoneId: selectedZone?.id,
              hostname: label + "." + selectedZone?.name,
              packageId: selectedApp?.packageId,
            },
            "App route request saved. Check the route status below.",
          );
        }}
      >
        <label>
          {t("Tunnel")}
          <select
            required
            disabled={busy}
            value={selectedTunnel?.id || ""}
            onChange={(e) => setTunnel(e.target.value)}
          >
            <option value="">{t("Choose a tunnel")}</option>
            {data.tunnels?.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("Domain")}
          <select
            required
            disabled={busy}
            value={selectedZone?.id || ""}
            onChange={(e) => setZone(e.target.value)}
          >
            <option value="">{t("Choose a domain")}</option>
            {zones.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("Installed app")}
          <select
            required
            disabled={busy}
            value={selectedApp?.packageId || ""}
            onChange={(e) => setApp(e.target.value)}
          >
            {data.apps?.map((row) => (
              <option key={row.packageId} value={row.packageId}>
                {row.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("Record name")}
          <input
            required
            aria-label={t("Record name")}
            pattern="[A-Za-z0-9][A-Za-z0-9.-]*"
            maxLength={100}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <small>
            {label || "app"}.{selectedZone?.name || "…"}
          </small>
        </label>
        <button
          disabled={busy || !selectedTunnel || !selectedZone || !selectedApp}
        >
          {t("Connect app domain")}
        </button>
      </form>
      {selectedTunnel && (
        <button
          disabled={busy}
          onClick={() =>
            void change(
              "/tunnels/" + selectedTunnel.id + "/install-connector",
              "POST",
              {},
              "Local tunnel connector installation completed.",
            )
          }
        >
          {t("Install local connector")}
        </button>
      )}
      {selectedTunnel && (
        <p role="status">
          {t("Local connector")}:{" "}
          {translateText(
            data.connectors?.[selectedTunnel.id]?.state || "Not installed",
          )}
        </p>
      )}
      <p className="muted">
        {t(
          "A synchronized route confirms DNS and routing configuration. Public HTTPS reachability is checked separately by Cloudflare Healthcheck.",
        )}
      </p>
      <div className="cloudflare-profile-list">
        {data.routes?.map((row) => (
          <article key={row.id}>
            <div>
              <strong>{row.hostname}</strong>
              <small>
                {row.packageId} · {translateText(row.status)}
              </small>
              <p role="status">{translateText(row.message)}</p>
            </div>
            <label>
              <input
                type="checkbox"
                checked={row.autoSync}
                disabled={busy}
                onChange={(e) =>
                  void change(
                    "/routes/" + row.id,
                    "PUT",
                    { autoSync: e.target.checked },
                    "Automatic synchronization updated",
                  )
                }
              />
              {t("Keep app route synchronized")}
            </label>
          </article>
        ))}
      </div>
    </section>
  );
}
