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
  cores: "2",
  memory: "2048",
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
  const guest = [
    "set -Eeuo pipefail",
    "umask 022",
    "[ \"$(id -u)\" -eq 0 ] || { echo 'Run as root.' >&2; exit 1; }",
    "[ ! -d /etc/pve ] || { echo 'Run the Linux installer inside the guest, not on Proxmox.' >&2; exit 1; }",
    ". /etc/os-release",
    '[ "$ID" = debian ] && [[ "$VERSION_ID" = 12 || "$VERSION_ID" = 13 ]] || { echo \'Debian 12 or 13 required.\' >&2; exit 1; }',
    `INSTALL_DIR=${quote(c.installPath)}`,
    `DATA_DIR=${quote(c.dataPath)}`,
    `APP_PORT=${quote(c.appPort)}`,
    `TZ=${quote(c.timezone)}`,
    "export INSTALL_DIR DATA_DIR APP_PORT TZ",
    '[ ! -e "$INSTALL_DIR" ] && [ ! -L "$INSTALL_DIR" ] || { echo \'Source path already exists; stopping.\' >&2; exit 1; }',
    '[ "$(realpath -m "$DATA_DIR")" = "$DATA_DIR" ] && [ "$(realpath -m "$INSTALL_DIR")" = "$INSTALL_DIR" ] || { echo \'Symlinked paths are not supported.\' >&2; exit 1; }',
    'if [ -d "$DATA_DIR" ] && [ -n "$(find "$DATA_DIR" -mindepth 1 -maxdepth 1 ! -name lost+found -print -quit)" ]; then echo \'App-data path is not empty; stopping.\' >&2; exit 1; fi',
    "export DEBIAN_FRONTEND=noninteractive",
    "apt-get update",
    "apt-get install -y ca-certificates curl git python3",
    "if ! command -v docker >/dev/null 2>&1; then",
    "  install -m 0755 -d /etc/apt/keyrings",
    "  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc",
    "  chmod 0644 /etc/apt/keyrings/docker.asc",
    "  cat > /etc/apt/sources.list.d/docker.sources <<DOCKER_REPO",
    "Types: deb",
    "URIs: https://download.docker.com/linux/debian",
    "Suites: $VERSION_CODENAME",
    "Components: stable",
    "Architectures: $(dpkg --print-architecture)",
    "Signed-By: /etc/apt/keyrings/docker.asc",
    "DOCKER_REPO",
    "  chmod 0644 /etc/apt/sources.list.d/docker.sources",
    "  apt-get update",
    "  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
    "fi",
    "systemctl enable --now docker",
    "docker compose version",
    'mkdir -p -- "$(dirname "$INSTALL_DIR")" "$DATA_DIR"',
    'git clone --depth 1 https://github.com/qlerup/fjordhub.git "$INSTALL_DIR"',
    'cd -- "$INSTALL_DIR"',
    "python3 - <<'MEDIAHUB_ENV'",
    "import os, secrets",
    "from pathlib import Path",
    "values = {key: os.environ[key] for key in ('DATA_DIR', 'APP_PORT', 'TZ')}",
    "values['FJORDHUB_HOST_DIR'] = os.environ['INSTALL_DIR']",
    "values['SECRET_KEY'] = secrets.token_hex(32)",
    "lines = Path('.env.example').read_text().splitlines()",
    "lines = [line for line in lines if line.partition('=')[0] not in values]",
    "with os.fdopen(os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:",
    "    output.write('\\n'.join(lines + [key + '=' + value for key, value in values.items()]) + '\\n')",
    "Path('.env').chmod(0o600)",
    "MEDIAHUB_ENV",
    "docker compose config --quiet",
    "docker compose up -d --build --wait --wait-timeout 180",
    "docker compose ps",
    'curl --fail --silent --show-error "http://127.0.0.1:$APP_PORT/api/health"',
    "printf '\\nFjordHub is ready. Open http://<guest-IP>:%s and create your administrator.\\n' \"$APP_PORT\"",
    "hostname -I",
  ].join("\n");
  if (c.target === "linux")
    return "bash <<'MEDIAHUB_INSTALL'\n" + guest + "\nMEDIAHUB_INSTALL";
  const network = `name=eth0,bridge=${c.bridge},ip=${c.network === "dhcp" ? "dhcp" : c.address + ",gw=" + c.gateway},ip6=manual`;
  return [
    "bash <<'MEDIAHUB_PROVISION'",
    "set -Eeuo pipefail",
    "[ \"$(id -u)\" -eq 0 ] && command -v pct >/dev/null || { echo 'Run in the Proxmox node shell as root.' >&2; exit 1; }",
    "[ \"$(dpkg --print-architecture)\" = amd64 ] || { echo 'This template requires amd64.' >&2; exit 1; }",
    c.ctid ? `CTID=${quote(c.ctid)}` : "CTID=$(pvesh get /cluster/nextid)",
    'pvesh get /cluster/nextid --vmid "$CTID" >/dev/null',
    `STORAGE=${quote(c.storage)}`,
    `TEMPLATE_STORAGE=${quote(c.templateStorage)}`,
    `ip link show ${quote(c.bridge)} >/dev/null`,
    'pvesm status --storage "$STORAGE" --content rootdir',
    'pvesm status --storage "$TEMPLATE_STORAGE" --content vztmpl',
    "pveam update",
    "TEMPLATE=$(pveam available --section system | awk '$2 ~ /^debian-13-standard_.*_amd64.tar.zst$/ {print $2}' | sort -V | tail -n 1)",
    "[ -n \"$TEMPLATE\" ] || { echo 'No Debian 13 template found.' >&2; exit 1; }",
    'pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"',
    `pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" --hostname ${quote(c.hostname)} --ostype debian --unprivileged 1 --features nesting=1,keyctl=1 --cores ${c.cores} --memory ${c.memory} --swap 512 --rootfs "$STORAGE:${c.disk}" --mp0 "$STORAGE:${c.dataDisk},mp=${c.dataPath},backup=1" --net0 ${quote(network)} --onboot 1`,
    'printf "Created LXC %s. If a later step fails, inspect this container before retrying.\\n" "$CTID"',
    'pct start "$CTID"',
    'pct exec "$CTID" -- bash -c \'for attempt in {1..30}; do getent hosts deb.debian.org >/dev/null && exit 0; sleep 2; done; echo "Guest network is not ready" >&2; exit 1\'',
    "pct exec \"$CTID\" -- bash -s <<'MEDIAHUB_GUEST'",
    guest,
    "MEDIAHUB_GUEST",
    'printf "Manage this guest with: pct enter %s\\n" "$CTID"',
    "MEDIAHUB_PROVISION",
  ].join("\n");
}
