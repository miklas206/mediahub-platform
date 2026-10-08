import { translateText, t } from "./i18n";

import { LayoutGroup } from "./page-layout";
import { FjordHubDeployment } from "./fjordhub-deployment";
import { FjordHubTokenGuide } from "./fjordhub-token-guide";
import { useEffect, useRef, useState } from "react";
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
    <LayoutGroup id="store-AppStorePage-1" className="stack app-store-page">
      <section className="store-hero">
        <div className="store-hero-icon">
          <Store size={28} />
        </div>
        <div>
          <p className="eyebrow">{t("MEDIAHUB APP STORE")}</p>
          <h2>{t("Add only what you need.")}</h2>
          <p>
            {t(
              "Guided setup keeps required choices visible, stores secrets safely and never changes DNS, storage or containers without a clear step.",
            )}
          </p>
        </div>
      </section>
      <CatalogPage showInstalled />
    </LayoutGroup>
  );
}

export function CloudflareStorePage() {
  const [saved, setSaved] = useState(false);
  return (
    <div className="stack store-install-page">
      <Link className="text-link" to="/store">
        {t("← Back to App Store")}
      </Link>
      <Panel title={t("What MediaHub can prepare")}>
        <div className="store-discovery-grid">
          <div>
            <Check size={18} />
            <strong>{t("Detected automatically")}</strong>
            <p>
              {t(
                "The current private MediaHub address, HTTPS protocol and the health endpoints used after setup.",
              )}
            </p>
          </div>
          <div>
            <PackagePlus size={18} />
            <strong>{t("You provide")}</strong>
            <p>
              {t(
                "The tunnel name, public hostname and any optional local metrics URL. Cloudflare itself provides the connector token for a new tunnel.",
              )}
            </p>
          </div>
          <div>
            <ShieldCheck size={18} />
            <strong>{t("Never requested")}</strong>
            <p>
              {t(
                "MediaHub does not need an account-wide Cloudflare API token and does not disable TLS certificate verification.",
              )}
            </p>
          </div>
        </div>
      </Panel>
      {saved && (
        <div className="success store-success" role="status">
          <Check size={18} />
          {t(
            "Cloudflare Tunnel is now registered. Future visits show saved profiles and “Edit configuration” instead of repeating first-time setup.",
          )}
          <Link to="/apps">{t("Open installed apps →")}</Link>
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
  const stepStart = useRef<HTMLDivElement>(null);
  const previousStep = useRef(step);
  useEffect(() => {
    if (previousStep.current === step) return;
    previousStep.current = step;
    stepStart.current?.focus({ preventScroll: true });
    stepStart.current?.scrollIntoView({ block: "start", behavior: "instant" });
  }, [step]);
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

  const navigation = (
    <div className="assisted-actions">
      <button
        type="button"
        disabled={step === 0 || deploying}
        onClick={() => setStep((value) => Math.max(0, value - 1))}
      >
        <ChevronLeft size={16} />
        {t(" Back")}
      </button>
      <span>
        {t("Step ")}
        {step + 1}
        {t(" of ")}
        {fjordHubSteps.length}: {translateText(fjordHubSteps[step])}
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
          {t("Continue to")}{" "}
          {translateText(
            fjordHubSteps[step === 0 && mode === "existing" ? 3 : step + 1],
          )}{" "}
          <ChevronRight size={16} />
        </button>
      ) : (
        <Link className="primary" to="/integrations">
          {t("Manage integrations →")}
        </Link>
      )}
    </div>
  );

  return (
    <div className="stack store-install-page">
      <Link className="text-link" to="/store">
        {t("← Back to App Store")}
      </Link>
      <Panel title={t("Guided FjordHub deployment")}>
        <div className="assisted-setup-intro">
          <div className="store-hero-icon">
            <PackagePlus size={22} />
          </div>
          <div>
            <strong>{t("Official source, explicit choices")}</strong>
            <p className="muted">
              {t(
                "MediaHub links to FjordHub’s public source and explains every host value. It does not silently mount the Docker socket or claim a port on your server.",
              )}
            </p>
          </div>
        </div>
        <ol
          className="assisted-steps"
          aria-label={t("FjordHub setup progress")}
        >
          {fjordHubSteps.map((label, index) => (
            <li
              className={
                index === step ? "current" : index < step ? "done" : ""
              }
              aria-current={index === step ? "step" : undefined}
              key={label}
            >
              <span>{index < step ? <Check size={14} /> : index + 1}</span>
              {translateText(label)}
            </li>
          ))}
        </ol>

        <div
          ref={stepStart}
          tabIndex={-1}
          className="fjordhub-step-navigation"
          role="group"
          aria-label={t("Step {value0} of {value1}: {value2}", {
            value0: step + 1,
            value1: fjordHubSteps.length,
            value2: fjordHubSteps[step],
          })}
        >
          {navigation}
        </div>

        {step === 0 && (
          <div className="assisted-step">
            <p className="eyebrow">{t("STEP 1 · DEPLOYMENT")}</p>
            <h3>{t("Do you already run FjordHub?")}</h3>
            <div className="setup-choice-grid">
              <button
                type="button"
                className={mode === "new" ? "selected" : ""}
                onClick={() => setMode("new")}
              >
                <strong>{t("Prepare a new installation")}</strong>
                <span>
                  {t("Use FjordHub’s official repository and Docker Compose.")}
                </span>
              </button>
              <button
                type="button"
                className={mode === "existing" ? "selected" : ""}
                onClick={() => setMode("existing")}
              >
                <strong>{t("Connect an existing FjordHub")}</strong>
                <span>
                  {t("Skip deployment and add its read-only Access Token.")}
                </span>
              </button>
            </div>
            <a
              href="https://github.com/qlerup/fjordhub"
              target="_blank"
              rel="noreferrer"
            >
              {t("Open the verified FjordHub source ")}
              <ExternalLink size={14} />
            </a>
          </div>
        )}

        {step === 1 && (
          <div className="assisted-step">
            <p className="eyebrow">{t("STEP 2 · STORAGE & PORTS")}</p>
            <h3>{t("Choose paths that survive container replacement")}</h3>
            <label>
              {t("Installation target")}
              <select
                value={config.target}
                onChange={(event) => field("target", event.target.value)}
              >
                <option value="lxc">{t("Create a new Proxmox LXC")}</option>
                <option value="linux">
                  {t("Use an existing Debian host")}
                </option>
              </select>
            </label>
            {config.target === "lxc" && (
              <>
                <p className="muted">
                  {t(
                    "Recommended: 4 CPU cores and 10 GiB RAM (10240 MiB). Debian 13, unprivileged LXC with Docker nesting. Storage names and bridge are defaults, not detected from your server. Use",
                  )}{" "}
                  <code>pvesm status</code>
                  {t(" and ")}
                  <code>ip link show</code>
                  {t(" in the Proxmox shell to check them.")}
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
                      {translateText(label)}
                      <input
                        value={config[key]}
                        onChange={(event) => field(key, event.target.value)}
                      />
                    </label>
                  ))}
                  <label>
                    {t("Network configuration")}
                    <select
                      value={config.network}
                      onChange={(event) => field("network", event.target.value)}
                    >
                      <option value="dhcp">{t("DHCP")}</option>
                      <option value="static">{t("Static IPv4")}</option>
                    </select>
                  </label>
                  {config.network === "static" && (
                    <>
                      <label>
                        {t("IPv4 address/prefix")}
                        <input
                          placeholder="192.168.1.50/24"
                          value={config.address}
                          onChange={(event) =>
                            field("address", event.target.value)
                          }
                        />
                      </label>
                      <label>
                        {t("IPv4 gateway")}
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
                {t("FjordHub source path")}
                <input
                  value={installPath}
                  onChange={(event) => field("installPath", event.target.value)}
                />
                <small>
                  {t("Dedicated folder for the Git checkout and Compose file.")}
                </small>
              </label>
              <label>
                {t("Persistent app-data path")}
                <input
                  value={dataPath}
                  onChange={(event) => field("dataPath", event.target.value)}
                />
                <small>
                  {t(
                    "Path inside the guest. LXC mode creates a separate managed data disk here, included in backups. Existing media folders must be mounted separately; selecting a storage pool does not import files.",
                  )}
                </small>
              </label>
              {config.target === "lxc" && (
                <p className="muted">
                  {t(
                    "LXC setup creates a dedicated read-only Proxmox API account (PVEAuditor across the cluster) and verifies storage discovery. The API connection uses FjordHub's default self-signed TLS mode without certificate verification. Use a trusted private network.",
                  )}
                </p>
              )}
              <label>
                {t("Direct FjordHub port")}
                <input
                  inputMode="numeric"
                  value={appPort}
                  onChange={(event) => field("appPort", event.target.value)}
                />
                <small>
                  {t("Confirm that this port is free on the selected host.")}
                </small>
              </label>
              <label>
                {t("Timezone")}
                <input
                  value={timezone}
                  onChange={(event) => field("timezone", event.target.value)}
                />
              </label>
            </div>
            {errors.length > 0 && (
              <div className="notice" role="alert">
                {errors.map((error) => (
                  <p key={error}>{translateText(error)}</p>
                ))}
              </div>
            )}
            <div className="setup-safety-note">
              <ShieldCheck size={20} />
              <p>
                {t(
                  "FjordHub controls Docker through the host socket, which is effectively administrator access to that Docker host. A dedicated trusted LXC or VM is recommended. Its bundled Traefik also uses ports 80 and 8080 unless you change them.",
                )}
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
            <p className="eyebrow">{t("STEP 4 · CONNECT READ-ONLY")}</p>
            <h3>{t("Create a FjordHub Access Token")}</h3>
            <FjordHubTokenGuide baseUrl={fjordHubUrl} />
            <div className="setup-safety-note">
              <HardDrive size={20} />
              <p>
                {t(
                  "Connecting FjordHub does not grant MediaHub write access to its storage, containers or users. It remains an optional external integration, not a MediaHub Agent.",
                )}
              </p>
            </div>
          </div>
        )}

        {navigation}
      </Panel>
      {step === 3 && (
        <IntegrationsPage onUrlChange={setFjordHubUrl} showTokenGuide={false} />
      )}
    </div>
  );
}
