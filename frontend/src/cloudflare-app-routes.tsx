import { useState } from "react";
import { t, translateText } from "./i18n";

export type AppRouting = {
  setup?: { state: string; phase: string; message: string; hostname?: string };
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
  const [manual, setManual] = useState(false);
  const settingUp = data.setup?.state === "running";
  const selectedTunnel =
    data.tunnels?.find((row) => row.id === tunnel) || data.tunnels?.[0];
  const selectedZone = zones.find((row) => row.id === zone) || zones[0];
  const selectedApp =
    data.apps?.find((row) => row.packageId === app) || data.apps?.[0];
  return (
    <section className="stack">
      <h3>{t("Connect an app")}</h3>
      <p className="muted">
        {t(
          "Choose an app and its address. MediaHub sets up the connection, DNS and app address automatically.",
        )}
      </p>
      <details>
        <summary>{t("Advanced connection settings")}</summary>
        <label>
          <input
            type="checkbox"
            checked={manual}
            disabled={busy || settingUp}
            onChange={(e) => setManual(e.target.checked)}
          />
          {t("Choose and manage a tunnel manually")}
        </label>
        <p className="muted">
          {t(
            "Automatic setup creates a dedicated connection for MediaHub and keeps your other tunnels unchanged.",
          )}
        </p>
        {manual && (
          <>
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
                  row.remote &&
                  !data.tunnels?.some((saved) => saved.id === row.id),
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
          </>
        )}
      </details>
      <form
        className="cloudflare-management-form"
        onSubmit={(e) => {
          e.preventDefault();
          void change(
            manual ? "/routes" : "/publish",
            "POST",
            {
              zoneId: selectedZone?.id,
              packageId: selectedApp?.packageId,
              ...(manual
                ? {
                    tunnelId: selectedTunnel?.id,
                    hostname: label + "." + selectedZone?.name,
                  }
                : { label }),
            },
            "Domain setup started. You can follow its progress here.",
          );
        }}
      >
        {manual && (
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
        )}
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
            maxLength={100}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <small>
            {label || "app"}.{selectedZone?.name || "…"}
          </small>
        </label>
        <button
          disabled={
            busy ||
            settingUp ||
            (manual && !selectedTunnel) ||
            !selectedZone ||
            !selectedApp
          }
        >
          {t(
            settingUp ? "Setting up domain..." : "Set up domain automatically",
          )}
        </button>
      </form>
      {data.setup && (
        <p role="status" className="cloudflare-setup-progress">
          {data.setup.hostname && <strong>{data.setup.hostname} · </strong>}
          {translateText(data.setup.message)}
        </p>
      )}
      {manual && selectedTunnel && (
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
      {manual && selectedTunnel && (
        <p role="status">
          {t("Local connector")}:{" "}
          {translateText(
            data.connectors?.[selectedTunnel.id]?.state || "Not installed",
          )}
        </p>
      )}
      <div className="cloudflare-profile-list">
        {data.routes?.map((row) => (
          <article key={row.id}>
            <div>
              <strong>{row.hostname}</strong>
              <small>
                {data.apps?.find((app) => app.packageId === row.packageId)
                  ?.name || row.packageId}{" "}
                · {translateText(row.status)}
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
