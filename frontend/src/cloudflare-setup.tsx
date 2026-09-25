import { useMemo, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Cloud,
  Pencil,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { api } from "./api";
import { ErrorBox, Panel, useLoad } from "./phase2";
import type { CatalogApp } from "./phase2-types";

const packageId = "org.mediahub.cloudflared";

function browserPrivateOrigin() {
  if (typeof window === "undefined") return "";
  const hostname = window.location.hostname.toLowerCase();
  const privateHostname =
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "::1" ||
    hostname.startsWith("10.") ||
    hostname.startsWith("192.168.") ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(hostname);
  return privateHostname ? window.location.origin : "";
}

type StoredConfiguration = {
  values: Record<string, string>;
  secrets: Record<string, { configured: boolean }>;
};

type SetupValues = {
  setup_mode: "existing-tunnel" | "new-tunnel";
  tunnel_name: string;
  public_hostnames: string;
  origin_url: string;
  status_url: string;
};

type TunnelProfile = {
  id: string;
  name: string;
  setupMode: "existing-tunnel" | "new-tunnel";
  publicHostnames: string[];
  originUrl: string;
  statusUrl: string;
};

const defaults: SetupValues = {
  setup_mode: "existing-tunnel",
  tunnel_name: "",
  public_hostnames: "",
  origin_url: browserPrivateOrigin(),
  status_url: "",
};

function routes(value: string) {
  return value
    .split(/[\s,;]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function storedProfiles(configuration?: StoredConfiguration): TunnelProfile[] {
  if (!configuration) return [];
  const raw = configuration.values.tunnel_profiles;
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (Array.isArray(parsed)) {
        return parsed
          .filter(
            (item): item is Record<string, unknown> =>
              !!item && typeof item === "object",
          )
          .slice(0, 8)
          .map((item, index) => ({
            id:
              typeof item.id === "string" && item.id
                ? item.id
                : `tunnel-${index + 1}`,
            name:
              typeof item.name === "string" && item.name
                ? item.name
                : `Tunnel ${index + 1}`,
            setupMode:
              item.setupMode === "new-tunnel"
                ? "new-tunnel"
                : "existing-tunnel",
            publicHostnames: Array.isArray(item.publicHostnames)
              ? item.publicHostnames.filter(
                  (hostname): hostname is string =>
                    typeof hostname === "string" && !!hostname,
                )
              : [],
            originUrl: typeof item.originUrl === "string" ? item.originUrl : "",
            statusUrl: typeof item.statusUrl === "string" ? item.statusUrl : "",
          }));
      }
    } catch {
      // Fall through to the legacy single-profile fields below.
    }
  }
  const legacyName = configuration.values.tunnel_name?.trim();
  const legacyRoutes = routes(configuration.values.public_hostnames || "");
  if (!legacyName && !legacyRoutes.length) return [];
  return [
    {
      id: "legacy",
      name: legacyName || "Cloudflare Tunnel",
      setupMode:
        configuration.values.setup_mode === "new-tunnel"
          ? "new-tunnel"
          : "existing-tunnel",
      publicHostnames: legacyRoutes,
      originUrl: configuration.values.origin_url || browserPrivateOrigin(),
      statusUrl: configuration.values.status_url || "",
    },
  ];
}

function CloudflareSetupEditor({
  profiles,
  profile,
  onFinished,
}: {
  profiles: TunnelProfile[];
  profile?: TunnelProfile;
  onFinished: (saved: boolean) => void;
}) {
  const catalog = useLoad<CatalogApp[]>("/catalog");
  const [values, setValues] = useState<SetupValues>(() =>
    profile
      ? {
          setup_mode: profile.setupMode,
          tunnel_name: profile.name,
          public_hostnames: profile.publicHostnames.join("\n"),
          origin_url: profile.originUrl,
          status_url: profile.statusUrl,
        }
      : { ...defaults, origin_url: browserPrivateOrigin() },
  );
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const app = catalog.data?.find((item) => item.id === packageId);
  const steps = app?.installGuide || [];
  const routeList = useMemo(
    () => routes(values.public_hostnames),
    [values.public_hostnames],
  );
  const valid =
    step === 0
      ? !!values.tunnel_name.trim()
      : step === 1
        ? !!routeList.length && /^https?:\/\//i.test(values.origin_url)
        : true;
  const update = (name: keyof SetupValues, value: string) =>
    setValues((current) => ({ ...current, [name]: value }));
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const savedProfile: TunnelProfile = {
        id: profile?.id || crypto.randomUUID(),
        name: values.tunnel_name.trim(),
        setupMode: values.setup_mode,
        publicHostnames: routeList,
        originUrl: values.origin_url.trim(),
        statusUrl: values.status_url.trim(),
      };
      const updated = profile
        ? profiles.map((item) => (item.id === profile.id ? savedProfile : item))
        : [...profiles, savedProfile];
      const primary = updated[0];
      await api(`/catalog/${packageId}/configuration`, "PUT", {
        values: {
          tunnel_profiles: JSON.stringify(updated),
          setup_mode: primary.setupMode,
          tunnel_name: primary.name,
          public_hostnames: primary.publicHostnames.join("\n"),
          origin_url: primary.originUrl,
          status_url: primary.statusUrl,
        },
      });
      onFinished(true);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel
      title={
        profile ? "Edit Cloudflare configuration" : "Assisted Cloudflare setup"
      }
    >
      <div className="assisted-setup-intro">
        <div className="tunnel-icon degraded">
          <Cloud size={22} />
        </div>
        <div>
          <strong>
            {profile
              ? `Edit ${profile.name}`
              : "Set up without command-line guesswork"}
          </strong>
          <p className="muted">
            MediaHub saves only non-secret monitoring details. It never receives
            an account-wide Cloudflare API token and never opens a router port.
          </p>
        </div>
      </div>
      <ol className="assisted-steps" aria-label="Cloudflare setup progress">
        {["Tunnel", "Routes", "Monitoring", "Review"].map((label, index) => (
          <li
            className={index === step ? "current" : index < step ? "done" : ""}
            key={label}
          >
            <span>{index < step ? <Check size={14} /> : index + 1}</span>
            {label}
          </li>
        ))}
      </ol>
      <ErrorBox error={error || catalog.error} />
      {step === 0 && (
        <div className="assisted-step">
          <p className="eyebrow">STEP 1 · TUNNEL</p>
          <h3>Are you using an existing tunnel?</h3>
          <div className="setup-choice-grid">
            <button
              className={
                values.setup_mode === "existing-tunnel" ? "selected" : ""
              }
              onClick={() => update("setup_mode", "existing-tunnel")}
              type="button"
            >
              <strong>Use an existing tunnel</strong>
              <span>
                Best when Cloudflare already shows the connector as healthy.
              </span>
            </button>
            <button
              className={values.setup_mode === "new-tunnel" ? "selected" : ""}
              onClick={() => update("setup_mode", "new-tunnel")}
              type="button"
            >
              <strong>Prepare a new tunnel</strong>
              <span>
                Follow Cloudflare's official creation flow, then return here.
              </span>
            </button>
          </div>
          <label>
            Tunnel name
            <input
              value={values.tunnel_name}
              onChange={(event) => update("tunnel_name", event.target.value)}
              placeholder="For example: My home tunnel"
              maxLength={100}
            />
            <small>A friendly label for the actual tunnel in Cloudflare.</small>
          </label>
          {values.setup_mode === "new-tunnel" && (
            <p className="notice">
              Create the tunnel in Cloudflare, deploy the shown connector, and
              add the published application. MediaHub deliberately does not ask
              for your account API token.{" "}
              {steps[1]?.helpUrl && (
                <a href={steps[1].helpUrl} target="_blank" rel="noreferrer">
                  Open official tunnel instructions →
                </a>
              )}
            </p>
          )}
        </div>
      )}
      {step === 1 && (
        <div className="assisted-step">
          <p className="eyebrow">STEP 2 · PUBLISHED ROUTES</p>
          <h3>Tell MediaHub which public routes to verify</h3>
          <p className="muted">
            One tunnel can publish several applications. Each hostname below is
            a route, not another tunnel.
          </p>
          <label>
            Public hostnames
            <textarea
              value={values.public_hostnames}
              onChange={(event) =>
                update("public_hostnames", event.target.value)
              }
              placeholder={"media.example.com\nhome.example.com"}
              rows={4}
            />
            <small>One per line, or separate them with commas.</small>
          </label>
          <label>
            Private MediaHub origin
            <input
              value={values.origin_url}
              onChange={(event) => update("origin_url", event.target.value)}
              placeholder="https://192.168.1.50:18765"
            />
            <small>
              The LAN service URL used in Cloudflare. Match the protocol
              exactly; an HTTPS-only MediaHub origin must start with https://.
            </small>
          </label>
        </div>
      )}
      {step === 2 && (
        <div className="assisted-step">
          <p className="eyebrow">STEP 3 · OPTIONAL CONNECTOR METRICS</p>
          <h3>Distinguish connector sessions from tunnels</h3>
          <p>
            Cloudflared normally keeps several redundant outbound sessions for
            one tunnel. A private metrics URL lets MediaHub show them
            accurately.
          </p>
          <label>
            Private metrics URL
            <input
              value={values.status_url}
              onChange={(event) => update("status_url", event.target.value)}
              placeholder="http://192.168.1.50:20241/metrics"
            />
            <small>Optional. Never expose this endpoint publicly.</small>
          </label>
          {steps[3]?.helpUrl && (
            <a href={steps[3].helpUrl} target="_blank" rel="noreferrer">
              Open official Cloudflare guidance →
            </a>
          )}
        </div>
      )}
      {step === 3 && (
        <div className="assisted-step">
          <p className="eyebrow">STEP 4 · REVIEW</p>
          <h3>Save this tunnel profile in MediaHub</h3>
          <div className="setup-review-grid">
            <span>Mode</span>
            <strong>
              {values.setup_mode === "existing-tunnel"
                ? "Existing tunnel"
                : "New tunnel"}
            </strong>
            <span>Tunnel label</span>
            <strong>{values.tunnel_name}</strong>
            <span>Published routes</span>
            <strong>{routeList.length}</strong>
            <span>Private origin</span>
            <strong>{values.origin_url}</strong>
            <span>Connector metrics</span>
            <strong>
              {values.status_url || "Not configured — route checks only"}
            </strong>
          </div>
          <div className="setup-safety-note">
            <ShieldCheck size={20} />
            <p>
              Saving updates MediaHub's monitoring configuration only. It does
              not change DNS, routes, tokens or connector processes in
              Cloudflare.
            </p>
          </div>
        </div>
      )}
      <div className="assisted-actions">
        <button
          disabled={busy}
          onClick={() => (step ? setStep(step - 1) : onFinished(false))}
        >
          <ChevronLeft size={16} /> {step ? "Back" : "Cancel"}
        </button>
        <span>{step + 1} of 4</span>
        {step < 3 ? (
          <button
            className="primary"
            disabled={!valid || busy}
            onClick={() => setStep(step + 1)}
          >
            Continue <ChevronRight size={16} />
          </button>
        ) : (
          <button
            className="primary"
            disabled={busy}
            onClick={() => void save()}
          >
            {busy ? "Saving…" : "Save configuration"}
          </button>
        )}
      </div>
    </Panel>
  );
}

export function CloudflareSetupManager({ onSaved }: { onSaved: () => void }) {
  const stored = useLoad<StoredConfiguration>(
    `/catalog/${packageId}/configuration`,
  );
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const profiles = useMemo(() => storedProfiles(stored.data), [stored.data]);
  const selected = profiles.find((profile) => profile.id === editing);
  const finish = (saved: boolean) => {
    setEditing(null);
    setAdding(false);
    if (saved) {
      stored.reload();
      onSaved();
      setMessage("Cloudflare monitoring configuration was saved.");
    }
  };
  const remove = async (profile: TunnelProfile) => {
    if (
      !window.confirm(
        `Remove the saved configuration for ${profile.name}? This does not delete anything in Cloudflare.`,
      )
    )
      return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = profiles.filter((item) => item.id !== profile.id);
      const primary = updated[0];
      await api(`/catalog/${packageId}/configuration`, "PUT", {
        values: {
          tunnel_profiles: JSON.stringify(updated),
          setup_mode: primary?.setupMode || "existing-tunnel",
          tunnel_name: primary?.name || "",
          public_hostnames: primary?.publicHostnames.join("\n") || "",
          origin_url: primary?.originUrl || "",
          status_url: primary?.statusUrl || "",
        },
      });
      stored.reload();
      onSaved();
      setMessage(`${profile.name} was removed from MediaHub monitoring.`);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (!stored.data)
    return (
      <Panel title="Cloudflare configuration">
        <p>Loading saved configuration…</p>
      </Panel>
    );
  if (adding || selected || !profiles.length)
    return (
      <CloudflareSetupEditor
        key={selected?.id || "new"}
        profiles={profiles}
        profile={selected}
        onFinished={finish}
      />
    );
  return (
    <Panel title="Saved Cloudflare configuration">
      <div className="assisted-setup-intro">
        <div className="tunnel-icon healthy">
          <Cloud size={22} />
        </div>
        <div>
          <strong>
            {profiles.length} tunnel configuration
            {profiles.length === 1 ? "" : "s"} saved
          </strong>
          <p className="muted">
            Edit existing monitoring details or add another tunnel. The guided
            installer appears only while adding or editing a configuration.
          </p>
        </div>
      </div>
      <ErrorBox error={error || stored.error} />
      <div className="cloudflare-profile-list">
        {profiles.map((profile) => (
          <article key={profile.id}>
            <div>
              <strong>{profile.name}</strong>
              <span>
                {profile.publicHostnames.length} published route
                {profile.publicHostnames.length === 1 ? "" : "s"}
              </span>
              <small>{profile.originUrl}</small>
            </div>
            <div className="button-row">
              <button onClick={() => setEditing(profile.id)}>
                <Pencil size={15} /> Edit configuration
              </button>
              <button disabled={busy} onClick={() => void remove(profile)}>
                <Trash2 size={15} /> Remove
              </button>
            </div>
          </article>
        ))}
      </div>
      <button className="primary" onClick={() => setAdding(true)}>
        <Plus size={16} /> Add tunnel configuration
      </button>
      {message && (
        <p className="success" role="status">
          {message}
        </p>
      )}
    </Panel>
  );
}
