import { FjordHubDeployment } from "./fjordhub-deployment";
import { FjordHubTokenGuide } from "./fjordhub-token-guide";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  HardDrive,
  PackagePlus,
  ShieldCheck,
  Store,
} from "lucide-react";
import { CloudflareSetupManager } from "./cloudflare-setup";
import { IntegrationsPage } from "./integrations";
import { CatalogPage, Panel } from "./phase2";
import {
  defaultFjordHubConfig,
  fjordHubErrors,
  type FjordHubConfig,
} from "./fjordhub-commands";

export function AppStorePage() {
  return (
    <div className="stack app-store-page">
      <section className="store-hero">
        <div className="store-hero-icon">
          <Store size={28} />
        </div>
        <div>
          <p className="eyebrow">MEDIAHUB APP STORE</p>
          <h2>Add only what you need.</h2>
          <p>
            Guided setup keeps required choices visible, stores secrets safely
            and never changes DNS, storage or containers without a clear step.
          </p>
        </div>
      </section>
      <CatalogPage showInstalled />
    </div>
  );
}

export function CloudflareStorePage() {
  const [saved, setSaved] = useState(false);
  return (
    <div className="stack store-install-page">
      <Link className="text-link" to="/store">
        ← Back to App Store
      </Link>
      <Panel title="What MediaHub can prepare">
        <div className="store-discovery-grid">
          <div>
            <Check size={18} />
            <strong>Detected automatically</strong>
            <p>
              The current private MediaHub address, HTTPS protocol and the
              health endpoints used after setup.
            </p>
          </div>
          <div>
            <PackagePlus size={18} />
            <strong>You provide</strong>
            <p>
              The tunnel name, public hostname and any optional local metrics
              URL. Cloudflare itself provides the connector token for a new
              tunnel.
            </p>
          </div>
          <div>
            <ShieldCheck size={18} />
            <strong>Never requested</strong>
            <p>
              MediaHub does not need an account-wide Cloudflare API token and
              does not disable TLS certificate verification.
            </p>
          </div>
        </div>
      </Panel>
      {saved && (
        <div className="success store-success" role="status">
          <Check size={18} />
          Cloudflare Tunnel is now registered. Future visits show saved profiles
          and “Edit configuration” instead of repeating first-time setup.
          <Link to="/apps">Open installed apps →</Link>
        </div>
      )}
      <CloudflareSetupManager onSaved={() => setSaved(true)} />
    </div>
  );
}

type FjordHubMode = "new" | "existing";

const fjordHubSteps = ["Deployment", "Storage & ports", "Install", "Connect"];

export function FjordHubStorePage() {
  const [fjordHubUrl, setFjordHubUrl] = useState("");
  const [step, setStep] = useState(0);
  const [deploying, setDeploying] = useState(false);
  const [mode, setMode] = useState<FjordHubMode>("new");
  const [config, setConfig] = useState<FjordHubConfig>({
    ...defaultFjordHubConfig,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  });
  const { installPath, dataPath, appPort, timezone } = config;
  const field = (key: keyof FjordHubConfig, value: string) =>
    setConfig((current) => ({ ...current, [key]: value }));
  const errors = fjordHubErrors(config);
  const canContinue = !deploying && (step !== 1 || errors.length === 0);

  return (
    <div className="stack store-install-page">
      <Link className="text-link" to="/store">
        ← Back to App Store
      </Link>
      <Panel title="Guided FjordHub deployment">
        <div className="assisted-setup-intro">
          <div className="store-hero-icon">
            <PackagePlus size={22} />
          </div>
          <div>
            <strong>Official source, explicit choices</strong>
            <p className="muted">
              MediaHub links to FjordHub’s public source and explains every host
              value. It does not silently mount the Docker socket or claim a
              port on your server.
            </p>
          </div>
        </div>
        <ol className="assisted-steps" aria-label="FjordHub setup progress">
          {fjordHubSteps.map((label, index) => (
            <li
              className={
                index === step ? "current" : index < step ? "done" : ""
              }
              key={label}
            >
              <span>{index < step ? <Check size={14} /> : index + 1}</span>
              {label}
            </li>
          ))}
        </ol>

        {step === 0 && (
          <div className="assisted-step">
            <p className="eyebrow">STEP 1 · DEPLOYMENT</p>
            <h3>Do you already run FjordHub?</h3>
            <div className="setup-choice-grid">
              <button
                type="button"
                className={mode === "new" ? "selected" : ""}
                onClick={() => setMode("new")}
              >
                <strong>Prepare a new installation</strong>
                <span>
                  Use FjordHub’s official repository and Docker Compose.
                </span>
              </button>
              <button
                type="button"
                className={mode === "existing" ? "selected" : ""}
                onClick={() => setMode("existing")}
              >
                <strong>Connect an existing FjordHub</strong>
                <span>Skip deployment and add its read-only Access Token.</span>
              </button>
            </div>
            <a
              href="https://github.com/qlerup/fjordhub"
              target="_blank"
              rel="noreferrer"
            >
              Open the verified FjordHub source <ExternalLink size={14} />
            </a>
          </div>
        )}

        {step === 1 && (
          <div className="assisted-step">
            <p className="eyebrow">STEP 2 · STORAGE & PORTS</p>
            <h3>Choose paths that survive container replacement</h3>
            <label>
              Installation target
              <select
                value={config.target}
                onChange={(event) => field("target", event.target.value)}
              >
                <option value="lxc">Create a new Proxmox LXC</option>
                <option value="linux">Use an existing Debian host</option>
              </select>
            </label>
            {config.target === "lxc" && (
              <>
                <p className="muted">
                  Recommended: 4 CPU cores and 10 GiB RAM (10240 MiB). Debian
                  13, unprivileged LXC with Docker nesting. Storage names and
                  bridge are defaults, not detected from your server. Use{" "}
                  <code>pvesm status</code> and <code>ip link show</code> in the
                  Proxmox shell to check them.
                </p>
                <div className="store-form-grid">
                  {(
                    [
                      ["ctid", "Container ID (empty = next free ID)"],
                      ["hostname", "Container hostname"],
                      ["templateStorage", "Template storage"],
                      ["storage", "Container disk storage"],
                      ["bridge", "Network bridge"],
                      ["cores", "CPU cores"],
                      ["memory", "Memory (MiB)"],
                      ["disk", "System disk (GiB)"],
                      ["dataDisk", "App-data disk (GiB)"],
                    ] as const
                  ).map(([key, label]) => (
                    <label key={key}>
                      {label}
                      <input
                        value={config[key]}
                        onChange={(event) => field(key, event.target.value)}
                      />
                    </label>
                  ))}
                  <label>
                    Network configuration
                    <select
                      value={config.network}
                      onChange={(event) => field("network", event.target.value)}
                    >
                      <option value="dhcp">DHCP</option>
                      <option value="static">Static IPv4</option>
                    </select>
                  </label>
                  {config.network === "static" && (
                    <>
                      <label>
                        IPv4 address/prefix
                        <input
                          placeholder="192.168.1.50/24"
                          value={config.address}
                          onChange={(event) =>
                            field("address", event.target.value)
                          }
                        />
                      </label>
                      <label>
                        IPv4 gateway
                        <input
                          placeholder="192.168.1.1"
                          value={config.gateway}
                          onChange={(event) =>
                            field("gateway", event.target.value)
                          }
                        />
                      </label>
                    </>
                  )}
                </div>
              </>
            )}
            <div className="store-form-grid">
              <label>
                FjordHub source path
                <input
                  value={installPath}
                  onChange={(event) => field("installPath", event.target.value)}
                />
                <small>
                  Dedicated folder for the Git checkout and Compose file.
                </small>
              </label>
              <label>
                Persistent app-data path
                <input
                  value={dataPath}
                  onChange={(event) => field("dataPath", event.target.value)}
                />
                <small>
                  Path inside the guest. LXC mode creates a separate managed
                  data disk here, included in backups. Existing media folders
                  must be mounted separately; selecting a storage pool does not
                  import files.
                </small>
              </label>
              {config.target === "lxc" && (
                <p className="muted">
                  LXC setup creates a dedicated read-only Proxmox API account
                  (PVEAuditor across the cluster) and verifies storage
                  discovery. The API connection uses FjordHub's default
                  self-signed TLS mode without certificate verification. Use a
                  trusted private network.
                </p>
              )}
              <label>
                Direct FjordHub port
                <input
                  inputMode="numeric"
                  value={appPort}
                  onChange={(event) => field("appPort", event.target.value)}
                />
                <small>
                  Confirm that this port is free on the selected host.
                </small>
              </label>
              <label>
                Timezone
                <input
                  value={timezone}
                  onChange={(event) => field("timezone", event.target.value)}
                />
              </label>
            </div>
            {errors.length > 0 && (
              <div className="notice" role="alert">
                {errors.map((error) => (
                  <p key={error}>{error}</p>
                ))}
              </div>
            )}
            <div className="setup-safety-note">
              <ShieldCheck size={20} />
              <p>
                FjordHub controls Docker through the host socket, which is
                effectively administrator access to that Docker host. A
                dedicated trusted LXC or VM is recommended. Its bundled Traefik
                also uses ports 80 and 8080 unless you change them.
              </p>
            </div>
          </div>
        )}

        <FjordHubDeployment
          config={config}
          visible={step === 2}
          onBusy={setDeploying}
        />

        {step === 3 && (
          <div className="assisted-step fjordhub-connect-step">
            <p className="eyebrow">STEP 4 · CONNECT READ-ONLY</p>
            <h3>Create a FjordHub Access Token</h3>
            <FjordHubTokenGuide baseUrl={fjordHubUrl} />
            <div className="setup-safety-note">
              <HardDrive size={20} />
              <p>
                Connecting FjordHub does not grant MediaHub write access to its
                storage, containers or users. It remains an optional external
                integration, not a MediaHub Agent.
              </p>
            </div>
          </div>
        )}

        <div className="assisted-actions">
          <button
            type="button"
            disabled={step === 0 || deploying}
            onClick={() => setStep((value) => Math.max(0, value - 1))}
          >
            <ChevronLeft size={16} /> Back
          </button>
          <span>
            {step + 1} of {fjordHubSteps.length}
          </span>
          {step < 3 ? (
            <button
              type="button"
              className="primary"
              disabled={!canContinue}
              onClick={() =>
                setStep((value) =>
                  value === 0 && mode === "existing" ? 3 : value + 1,
                )
              }
            >
              Continue <ChevronRight size={16} />
            </button>
          ) : (
            <Link className="primary" to="/integrations">
              Manage integrations →
            </Link>
          )}
        </div>
      </Panel>
      {step === 3 && (
        <IntegrationsPage onUrlChange={setFjordHubUrl} showTokenGuide={false} />
      )}
    </div>
  );
}
