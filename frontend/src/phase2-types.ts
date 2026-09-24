export type NetworkConfig = {
  listen_host: string;
  port: number;
  base_url: string;
  allowed_origins: string[];
  trusted_proxies: string[];
};
export type PlannedStorage = {
  name: string;
  kind: string;
  path: string;
  action: "existing" | "create";
  confirmed_path: string | null;
};
export type SetupDraft = {
  step: number;
  installation_type: "new" | "import";
  storage: PlannedStorage[];
  network: NetworkConfig;
  selected_apps: string[];
  selected_imports: string[];
};
export type SetupState = {
  setup_required: boolean;
  setup_completed: boolean;
  setup_version: number;
  revision: number;
  draft: SetupDraft;
};
export type Check = { name: string; state: string; message: string };
export type Checks = { core: Check[]; runtime: Check[] };
export type Inspection = {
  path: string;
  exists: boolean;
  directory: boolean;
  readable: boolean;
  writable: boolean;
  owner: string | null;
  uid: number | null;
  gid: number | null;
  permissions: string | null;
  filesystem: string | null;
  freeBytes: number;
  totalBytes: number;
};
export type DirectoryListing = {
  path: string | null;
  parent: string | null;
  folders: { name: string; path: string }[];
  capacity: Inspection | null;
};
export type MediaFileListing = {
  location: { id: string; name: string; kind: string; path: string };
  path: string;
  parent: string | null;
  items: {
    name: string;
    path: string;
    type: "folder" | "file";
    sizeBytes: number | null;
    modifiedAt: number;
  }[];
  truncated: boolean;
};
export type AgentStatus = {
  connected: boolean;
  version: string | null;
  hostname?: string;
  message?: string;
  fixtureMode?: boolean;
  createEnabled?: boolean;
  docker: { available: boolean; version?: string; composeAvailable?: boolean };
};
export type CatalogApp = {
  id: string;
  name: string;
  description: string;
  version: string;
  category: string;
  availability: string;
  requiredRuntime: string;
  recommendedIsolation?: string;
  hostCapabilities?: string[];
  maintainer: { name: string };
  capabilities: string[];
  storageRequirements: {
    id: string;
    type: string;
    required: boolean;
    access: string;
  }[];
  configFields: {
    name: string;
    label: string;
    type: "text" | "select" | "password";
    secret: boolean;
    required: boolean;
    options: string[];
    default: string | null;
  }[];
};
export type Discovery = {
  source: string;
  warning?: string;
  containers: {
    id: string;
    name: string;
    image: string;
    status: string;
    environmentNames: string[];
    networkMode: string;
    networks: string[];
    mounts: { source: string; target: string; writable: boolean }[];
    ports: { hostPort: number; container: string }[];
    candidates: { app: string; confidence: string; reason: string }[];
  }[];
  relationships: { sourceId: string; targetId: string; type: string }[];
};
export type ImportPlan = {
  source_id: string;
  source_type: string;
  detected_app: string;
  status: string;
  findings: string[];
  executable: false;
  target_app: string;
  source_paths: string[];
};
export type Review = {
  revision: number;
  draft: SetupDraft;
  warnings: string[];
  errors: string[];
  canApply: boolean;
  imports: ImportPlan[];
  actions: string[];
  willMigrate: false;
};
export const defaultNetwork: NetworkConfig = {
  listen_host: "127.0.0.1",
  port: 18765,
  base_url: "http://127.0.0.1:18765",
  allowed_origins: ["http://127.0.0.1:18765"],
  trusted_proxies: [],
};
export const defaultDraft: SetupDraft = {
  step: 0,
  installation_type: "new",
  storage: [],
  network: defaultNetwork,
  selected_apps: [],
  selected_imports: [],
};
