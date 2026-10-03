export type Health = {
  status: "healthy" | "degraded" | "unhealthy" | "unknown";
  summary: string;
  lastChecked: string;
  checks: { name: string; status: string; message: string }[];
};
export type AppInfo = {
  id: string;
  name: string;
  packageId: string;
  version: string;
  state: string;
  isMock: boolean;
  detailPath?: string | null;
  health: Health;
};
export type User = {
  id: string;
  username: string;
  role: string;
  csrf: string;
  language?: "en" | "da";
};
export type Metrics = {
  hostname: string;
  version: string;
  timestamp: string;
  uptimeSeconds: number;
  coreUptimeSeconds: number;
  environment: string;
  cpu: { percent: number | null; cores: number; scope: string };
  ram: {
    totalBytes: number;
    usedBytes: number;
    availableBytes: number;
    cacheBytes: number | null;
    percent: number;
    scope: string;
  };
  disk: {
    totalBytes: number;
    usedBytes: number;
    freeBytes: number;
    percent: number;
    scope: string;
  };
  network: {
    uploadBytesPerSecond: number | null;
    downloadBytesPerSecond: number | null;
  };
};
export type Activity = {
  id: string;
  timestamp: string;
  source: string;
  event: string;
  severity: string;
  message: string;
};
export type Storage = {
  owner?: string | null;
  uid?: number | null;
  gid?: number | null;
  permissions?: string | null;
  filesystem?: string | null;
  id: string;
  name: string;
  kind: string;
  path: string;
  exists: boolean;
  readable: boolean;
  writable: boolean;
  totalBytes: number | null;
  freeBytes: number | null;
  error?: string;
};
export type Settings = {
  display_name: string;
  theme: "dark" | "light" | "system";
  activity_page_size: number;
  advanced_mode: boolean;
  release_repository: string | null;
  update_check_interval_hours: 0 | 1 | 6 | 12 | 24 | 72 | 168;
  visible_navigation: NavigationPath[];
  dashboard_sections: DashboardSection[];
};
export type NavigationPath =
  | "/"
  | "/apps"
  | "/store"
  | "/storage"
  | "/hosts"
  | "/activity"
  | "/logs"
  | "/updates"
  | "/backups"
  | "/integrations"
  | "/settings";
export type DashboardSection =
  | "system"
  | "storage"
  | "apps"
  | "activity"
  | "network"
  | "core"
  | "runtime"
  | "integrations"
  | "cloudflare";
export type Log = {
  timestamp: string;
  level: string;
  component: string;
  message: string;
  requestId: string | null;
};
