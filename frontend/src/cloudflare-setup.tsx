import { useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Cloud,
  ShieldCheck,
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

export function CloudflareAssistedSetup({
  configured,
  onSaved,
}: {
  configured?: boolean;
  onSaved: () => void;
}) {
  const catalog = useLoad<CatalogApp[]>("/catalog");
  const stored = useLoad<StoredConfiguration>(
    `/catalog/${packageId}/configuration`,
  );
  const [values, setValues] = useState<SetupValues>(defaults);
  const [step, setStep] = useState(0);
  const [initialized, setInitialized] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const app = catalog.data?.find((item) => item.id === packageId);
  const steps = app?.installGuide || [];

  useEffect(() => {
    if (!stored.data || initialized) return;
    setValues({
      setup_mode:
        stored.data.values.setup_mode === "new-tunnel"
          ? "new-tunnel"
          : "existing-tunnel",
      tunnel_name: stored.data.values.tunnel_name || "",
      public_hostnames: stored.data.values.public_hostnames || "",
      origin_url: stored.data.values.origin_url || browserPrivateOrigin(),
      status_url: stored.data.values.status_url || "",
    });
    setInitialized(true);
  }, [initialized, stored.data]);

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
    setMessage("");
    try {
      await api(`/catalog/${packageId}/configuration`, "PUT", { values });
      stored.reload();
      onSaved();
      setMessage(
        "Setup saved. MediaHub reloaded read-only route and connector monitoring.",
      );
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Assisted Cloudflare setup">
      <div className="assisted-setup-intro">
        <div className="tunnel-icon degraded">
          <Cloud size={22} />
        </div>
        <div>
          <strong>
            {configured
              ? "Review or change the setup"
              : "Set up without command-line guesswork"}
          </strong>
          <p className="muted">
            MediaHub never receives an account-wide Cloudflare API token and
            never opens a router port.
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
      <ErrorBox error={error || stored.error || catalog.error} />
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
                Best when Cloudflare already shows your connector as healthy.
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
            <small>
              This is a friendly label. MediaHub does not claim that connector
              sessions are separate tunnels.
            </small>
          </label>
          {values.setup_mode === "new-tunnel" && (
            <p className="notice">
              Create a remotely managed tunnel in Cloudflare, deploy its
              connector using Cloudflare's shown installation command, and add
              the MediaHub published application. MediaHub deliberately does not
              ask for your account API token.
              {steps[1]?.helpUrl && (
                <>
                  {" "}
                  <a href={steps[1].helpUrl} target="_blank" rel="noreferrer">
                    Open official tunnel instructions →
                  </a>
                </>
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
              This is the LAN address entered as the route's service in
              Cloudflare. HTTPS is recommended.
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
            one tunnel. A local metrics URL lets MediaHub show those sessions,
            requests and errors accurately.
          </p>
          <label>
            Private metrics URL
            <input
              value={values.status_url}
              onChange={(event) => update("status_url", event.target.value)}
              placeholder="http://192.168.1.50:20241/metrics"
            />
            <small>
              Optional. Use cloudflared's private Prometheus /metrics endpoint
              or MediaHub's sanitized /status helper. Never expose it publicly.
            </small>
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
          <h3>Nothing is changed in your Cloudflare account</h3>
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
              Saving enables read-only checks. It does not create tunnels,
              change DNS, restart cloudflared or publish a new hostname.
            </p>
          </div>
        </div>
      )}
      <div className="assisted-actions">
        <button disabled={step === 0 || busy} onClick={() => setStep(step - 1)}>
          <ChevronLeft size={16} /> Back
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
            {busy ? "Saving…" : "Save and verify"}
          </button>
        )}
      </div>
      {message && (
        <p className="success" role="status">
          {message}
        </p>
      )}
    </Panel>
  );
}
