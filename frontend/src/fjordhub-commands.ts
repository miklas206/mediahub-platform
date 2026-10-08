import templates from "../../backend/mediahub/fjordhub_scripts.json";
export type FjordHubConfig = {
  target: "lxc" | "linux";
  installPath: string;
  dataPath: string;
  appPort: string;
  timezone: string;
  ctid: string;
  hostname: string;
  templateStorage: string;
  storage: string;
  bridge: string;
  cores: string;
  memory: string;
  disk: string;
  dataDisk: string;
  network: "dhcp" | "static";
  address: string;
  gateway: string;
};

export const defaultFjordHubConfig: FjordHubConfig = {
  target: "lxc",
  installPath: "/opt/fjordhub",
  dataPath: "/srv/mediahub/appdata/fjordhub",
  appPort: "8888",
  timezone: "Europe/Copenhagen",
  ctid: "",
  hostname: "fjordhub",
  templateStorage: "local",
  storage: "local-lvm",
  bridge: "vmbr0",
  cores: "4",
  memory: "10240",
  disk: "24",
  dataDisk: "32",
  network: "dhcp",
  address: "",
  gateway: "",
};

const numberIn = (value: string, min: number, max: number) =>
  /^\d+$/.test(value) && Number(value) >= min && Number(value) <= max;
const ipv4 = (value: string) =>
  /^(\d{1,3}\.){3}\d{1,3}$/.test(value) &&
  value
    .split(".")
    .every((part) => Number(part) <= 255 && String(Number(part)) === part) &&
  Number(value.split(".")[0]) > 0 &&
  Number(value.split(".")[0]) < 224;
const pathValid = (path: string) =>
  /^\/(opt|srv|mnt)\/[A-Za-z0-9_./-]+$/.test(path) &&
  path
    .split("/")
    .slice(1)
    .every((part) => part && part !== "." && part !== "..");
const quote = (value: string) => "'" + value.replaceAll("'", "'\\''") + "'";

export function fjordHubErrors(c: FjordHubConfig): string[] {
  const errors: string[] = [];
  if (!pathValid(c.installPath) || !pathValid(c.dataPath))
    errors.push(
      "Use dedicated absolute paths under /opt, /srv or /mnt, without spaces or .. segments.",
    );
  if (
    c.installPath === c.dataPath ||
    c.installPath.startsWith(c.dataPath + "/") ||
    c.dataPath.startsWith(c.installPath + "/")
  )
    errors.push(
      "Source and app-data paths must be separate, not inside each other.",
    );
  if (!numberIn(c.appPort, 1, 65535) || [80, 8080].includes(Number(c.appPort)))
    errors.push(
      "Choose a port from 1 to 65535 other than Traefik's ports 80 and 8080.",
    );
  try {
    new Intl.DateTimeFormat("en", { timeZone: c.timezone });
  } catch {
    errors.push("Enter a valid timezone, such as Europe/Copenhagen.");
  }
  if (!/^[A-Za-z0-9_+/-]+$/.test(c.timezone))
    errors.push("Timezone contains unsupported characters.");
  if (c.target === "lxc") {
    if (c.ctid && !numberIn(c.ctid, 100, 999999999))
      errors.push(
        "Container ID must be 100–999999999, or empty for automatic allocation.",
      );
    if (!/^[a-zA-Z][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]$/.test(c.hostname))
      errors.push("Use a hostname of 2–63 letters, numbers or hyphens.");
    if (
      ![c.storage, c.templateStorage].every((v) =>
        /^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(v),
      )
    )
      errors.push("Enter valid Proxmox storage IDs.");
    if (!/^[A-Za-z][A-Za-z0-9_.-]{0,14}$/.test(c.bridge))
      errors.push("Enter a valid network bridge, such as vmbr0.");
    if (
      !numberIn(c.cores, 1, 128) ||
      !numberIn(c.memory, 1024, 1048576) ||
      !numberIn(c.disk, 16, 65536) ||
      !numberIn(c.dataDisk, 1, 65536)
    )
      errors.push(
        "Use 1–128 CPU cores, at least 1024 MiB RAM, at least 16 GiB system disk and at least 1 GiB data disk.",
      );
    const [ip, prefix, extra] = c.address.split("/");
    if (
      c.network === "static" &&
      (!ipv4(ip || "") ||
        !numberIn(prefix || "", 1, 32) ||
        extra !== undefined ||
        !ipv4(c.gateway))
    )
      errors.push(
        "Enter an IPv4 address with prefix (for example 192.168.1.50/24) and an IPv4 gateway.",
      );
  }
  return errors;
}

export function fjordHubCommands(c: FjordHubConfig): string {
  const errors = fjordHubErrors(c);
  if (errors.length) throw new Error(errors.join(" "));
  const render = (template: string, values: Record<string, string>) =>
    template.replace(/@@([A-Za-z]+)@@/g, (_, key: string) => values[key]);
  const guest = render(templates.guest, c);
  if (c.target === "linux")
    return "bash <<'MEDIAHUB_INSTALL'\n" + guest + "\nMEDIAHUB_INSTALL";
  return render(templates.lxc, {
    ...c,
    guest,
    proxmox: templates.proxmox,
    ctidLine: c.ctid
      ? `CTID=${quote(c.ctid)}`
      : "CTID=$(pvesh get /cluster/nextid)",
    networkSpec: `name=eth0,bridge=${c.bridge},ip=${c.network === "dhcp" ? "dhcp" : c.address + ",gw=" + c.gateway},ip6=manual`,
  });
}
