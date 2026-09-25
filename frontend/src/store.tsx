import { useMemo, useState } from "react";
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
const linuxPath = /^\/[A-Za-z0-9._/-]+$/;

export function FjordHubStorePage() {
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<FjordHubMode>("new");
  const [installPath, setInstallPath] = useState("/opt/fjordhub");
  const [dataPath, setDataPath] = useState("/srv/mediahub/appdata/fjordhub");
  const [appPort, setAppPort] = useState("8888");
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  );
  const validPaths = linuxPath.test(installPath) && linuxPath.test(dataPath);
  const validPort = /^\d{2,5}$/.test(appPort) && Number(appPort) <= 65535;
  const installCommands = useMemo(
    () =>
      [
        `git clone --depth 1 https://github.com/qlerup/fjordhub.git ${installPath}`,
        `cd ${installPath}`,
        "cp .env.example .env",
        "openssl rand -hex 32  # copy this result to SECRET_KEY in .env",
        "docker compose up -d --build",
      ].join("\n"),
    [installPath],
  );
  const canContinue =
    step === 0 || step === 3 || (step === 1 ? validPaths && validPort : true);

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
            <div className="store-form-grid">
              <label>
                FjordHub source path
                <input
                  value={installPath}
                  onChange={(event) => setInstallPath(event.target.value)}
                />
                <small>
                  Dedicated folder for the Git checkout and Compose file.
                </small>
              </label>
              <label>
                Persistent app-data path
                <input
                  value={dataPath}
                  onChange={(event) => setDataPath(event.target.value)}
                />
                <small>
                  Use a writable MediaHub appdata mapping, not an OS root disk.
                </small>
              </label>
              <label>
                Direct FjordHub port
                <input
                  inputMode="numeric"
                  value={appPort}
                  onChange={(event) => setAppPort(event.target.value)}
                />
                <small>
                  Confirm that this port is free on the selected host.
                </small>
              </label>
              <label>
                Timezone
                <input
                  value={timezone}
                  onChange={(event) => setTimezone(event.target.value)}
                />
              </label>
            </div>
            {(!validPaths || !validPort) && (
              <p className="notice">
                Use absolute Linux paths without spaces and a valid port between
                10 and 65535.
              </p>
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

        {step === 2 && (
          <div className="assisted-step">
            <p className="eyebrow">STEP 3 · INSTALL FROM THE OFFICIAL SOURCE</p>
            <h3>Run these commands on the selected Linux host</h3>
            <pre className="install-command-block">{installCommands}</pre>
            <div className="setup-review-grid">
              <span>DATA_DIR in .env</span>
              <strong>{dataPath}</strong>
              <span>APP_PORT in .env</span>
              <strong>{appPort}</strong>
              <span>TZ in .env</span>
              <strong>{timezone}</strong>
              <span>SECRET_KEY in .env</span>
              <strong>Use the generated random value; never commit it</strong>
            </div>
            <p className="muted">
              After the containers are healthy, open FjordHub on the direct port
              and finish its own administrator setup. MediaHub deliberately does
              not execute unreviewed Git source as root.
            </p>
          </div>
        )}

        {step === 3 && (
          <div className="assisted-step fjordhub-connect-step">
            <p className="eyebrow">STEP 4 · CONNECT READ-ONLY</p>
            <h3>Create a FjordHub Access Token</h3>
            <p>
              In FjordHub, open Settings → Access Tokens, create a token and
              copy it once. Enter it below. MediaHub encrypts the token and uses
              only FjordHub’s read-only integration API.
            </p>
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
            disabled={step === 0}
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
      {step === 3 && <IntegrationsPage />}
    </div>
  );
}
