import { expect, it } from "vitest";
import {
  defaultFjordHubConfig as defaults,
  fjordHubCommands,
  fjordHubErrors,
} from "./fjordhub-commands";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

it("generates separate LXC disks and configures chosen values without exposing a secret", () => {
  const commands = fjordHubCommands({
    ...defaults,
    ctid: "210",
    storage: "ssd",
    appPort: "9090",
    timezone: "UTC",
  });
  expect(commands).toContain("CTID='210'");
  expect(commands).toContain('--vmid "$CTID"');
  expect(commands).toContain("--unprivileged 1 --features nesting=1,keyctl=1");
  expect(commands).toContain(
    '--mp0 "$STORAGE:32,mp=/srv/mediahub/appdata/fjordhub,backup=1"',
  );
  expect(commands).toContain("STORAGE='ssd'");
  expect(commands).toContain("APP_PORT='9090'");
  expect(commands).toContain("TZ='UTC'");
  expect(commands).toContain("secrets.token_hex(32)");
  expect(commands).toContain("values['FJORDHUB_HOST_DIR']");
  expect(commands).toContain("docker compose config --quiet");
  expect(commands).toContain('bash -s -- "$CTID"');
  expect(commands).toContain('"PROXMOX_VMID": sys.argv[4]');
  expect(commands).toContain("--roles PVEAuditor");
  expect(commands).toContain("Proxmox storage, disks and LXC mount discovery verified.");
  expect(commands).not.toContain("pct destroy");
  expect(commands).not.toContain("--privileged");
});

it("supports DHCP, static networking and existing Debian hosts", () => {
  expect(fjordHubCommands(defaults)).toContain(
    "CTID=$(pvesh get /cluster/nextid)",
  );
  expect(fjordHubCommands(defaults)).toContain("ip=dhcp");
  expect(
    fjordHubCommands({
      ...defaults,
      network: "static",
      address: "192.168.1.50/24",
      gateway: "192.168.1.1",
    }),
  ).toContain("ip=192.168.1.50/24,gw=192.168.1.1");
  const linux = fjordHubCommands({ ...defaults, target: "linux" });
  expect(linux).not.toContain("pct create");
  expect(linux).not.toContain("pveum user add");
  expect(linux).toContain("Source path already exists; stopping.");
  expect(linux).toContain("App-data path is not empty; stopping.");
});

it("rejects injection, invalid resources, unsafe paths and conflicting ports", () => {
  for (const changed of [
    { hostname: "x;touch /tmp/test" },
    { storage: "ssd,$(id)" },
    { timezone: "UTC\nCOMMAND=bad" },
    { installPath: "/opt/../etc" },
    { dataPath: "/etc" },
    { dataPath: "/opt/fjordhub/data" },
    { bridge: "vmbr0,ip=dhcp" },
    { appPort: "8080" },
    { appPort: "65536" },
    { memory: "0" },
    {
      network: "static" as const,
      address: "192.168.1.999/24",
      gateway: "192.168.1.1",
    },
  ]) {
    expect(fjordHubErrors({ ...defaults, ...changed }).length).toBeGreaterThan(
      0,
    );
    expect(() => fjordHubCommands({ ...defaults, ...changed })).toThrow();
  }
});

it("generated scripts pass Bash syntax checks without executing commands", () => {
  const bash =
    process.platform === "win32"
      ? "C:/Program Files/Git/bin/bash.exe"
      : "/bin/bash";
  expect(existsSync(bash)).toBe(true);
  for (const target of ["lxc", "linux"] as const) {
    const commands = fjordHubCommands({ ...defaults, target });
    execFileSync(bash, ["-n"], { input: commands });
    const guest =
      target === "lxc"
        ? commands
            .split("-- bash -s <<'MEDIAHUB_GUEST'\n")[1]
            .split("\nMEDIAHUB_GUEST")[0]
        : commands
            .split("bash <<'MEDIAHUB_INSTALL'\n")[1]
            .split("\nMEDIAHUB_INSTALL")[0];
    execFileSync(bash, ["-n"], { input: guest });
    const python =
      process.platform === "win32"
        ? resolve("../.venv/Scripts/python.exe")
        : "python3";
    const environmentCode = guest
      .split("python3 - <<'MEDIAHUB_ENV'\n")[1]
      .split("\nMEDIAHUB_ENV")[0];
    execFileSync(
      python,
      [
        "-c",
        "import sys; compile(sys.stdin.read(), '<generated-env>', 'exec')",
      ],
      { input: environmentCode },
    );
    const folder = resolve("../.qa/fjordhub-commands");
    mkdirSync(folder, { recursive: true });
    writeFileSync(resolve(folder, `${target}.sh`), commands);
  }
});
