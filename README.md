# MediaHub beta · fjordcopy

MediaHub is the primary hub for your self-hosted apps: one start page to open apps, install new ones, manage users and monitor the host. This independent project is based on [qlerup/FjordHub](https://github.com/qlerup/fjordhub).

The repository is **[miklas206/fjordcopy](https://github.com/miklas206/fjordcopy)**. It is separate from the earlier `mediahub-platform` project and uses a fresh database. Existing MediaHub data is not automatically migrated.

## What the hub does

- **Your apps:** installed Docker apps and built-in packages on the start page, with search, status and launch links.
- **App catalog:** FjordFlix, FjordLens, Fjord3D, FjordParcel, FjordBudget, FjordVPN, FjordSeed, OrbitMap and Urban Explorer; installation settings are defined by each app's manifest.
- **App lifecycle:** install, start, stop, update and remove apps using the existing FjordHub mechanisms.
- **Shared accounts:** administrator and user roles, app access, and the FjordHub-compatible authentication and SSO APIs.
- **Host management:** resource usage, storage configuration and update status.
- **Built-in packages:** Calendar and Whiteboard, installed separately from the App Store.

The product name is MediaHub. Internal `fjordhub` service names, manifest schemas, environment variables and `fjord-net` remain for compatibility with the apps. App repositories remain independent upstream projects.

## Install on a dedicated beta Docker host

Requirements: Linux with Git, Docker and the Compose plugin. Use a dedicated host/LXC: this stack retains fixed FjordHub container and network names and controls Docker through its socket.

```sh
git clone git@github.com:miklas206/fjordcopy.git /opt/fjordcopy
cd /opt/fjordcopy
cp .env.example .env
```

Edit `.env` before starting. Set a strong random `SECRET_KEY`, and use absolute paths for `DATA_DIR`, `APPS_DIR` and `FJORDHUB_HOST_DIR`. The data and apps directories must exist. Example values are `/opt/fjordcopy-data`, `/opt/fjordcopy-apps` and `/opt/fjordcopy` respectively. Keep `.env` readable only by the administrator.

```sh
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8091/api/health
```

Open `http://<beta-host>/` through Traefik, or `http://<beta-host>:8091/` directly. The first visit creates the administrator. SMTP and storage can be configured in the guide or later in Settings. No default administrator password is shipped.

The copied application catalog and package catalog are loaded from this checkout by default, so a private GitHub repository needs no runtime access token for catalog discovery. App manifests and app/package downloads still use their published upstream locations and need network access. `REGISTRY_URL` and `PACKAGES_URL` can override the catalog sources.

## Updates from this repository

The hub updater follows the checkout's `origin/main` and checks that its origin matches `FJORDCOPY_REPOSITORY` (default `miklas206/fjordcopy`). It must not pull hub code from the original FjordHub repository.

For this private repository, create a dedicated **read-only GitHub deploy key**. Store its private key at `DATA_DIR/git-ssh/id_ed25519` and GitHub's verified host keys at `DATA_DIR/git-ssh/known_hosts`. The updater mounts that directory read-only. Do not use a personal account token or copy a key from another service. Configure the checkout's host-side `core.sshCommand` to use the same key with `BatchMode=yes`, `IdentitiesOnly=yes` and `StrictHostKeyChecking=yes`.

The initial installation does not grant Proxmox access or attach media storage. Configure the intended host and permissions explicitly before using infrastructure features.

## Persistent state and recovery

- `DATA_DIR`: authentication database, settings, app installation state, packages, updater logs and deployment key.
- `APPS_DIR`: managed app checkouts and their local state; apps may use additional configured paths or Docker volumes.
- `.env`: deployment settings and session secret, outside version control.

Back up these together before upgrades. For the first beta deployment, take a LXC snapshot before installing. Keep any previous beta application available until the replacement is verified. Stop this stack with `docker compose stop`; do not remove volumes or restore an entire LXC snapshot after accepting new data without first backing up that data.

## Development checks

Use Python 3.11 or newer in an isolated environment. Install `requirements.txt`, `pytest` and `playwright`; install Playwright's Chromium browser for browser checks. Set `DATA_DIR` and `APPS_DIR` to disposable test directories before importing the application. Tests must not connect to a production Docker host.

```sh
python -m pytest tests/test_mediahub_launcher.py tests/test_device_login.py tests/test_onboarding.py tests/test_packages.py
git diff --check
```

## Origin and attribution

Imported from **qlerup/fjordhub**, commit `b63d176985cecdd6a8f88588d62f6d74e197598f`. Original Git history and assets are retained. The original project documentation is preserved in [docs/upstream-fjordhub.md](docs/upstream-fjordhub.md); its upstream installation commands refer to the original project.

The upstream checkout did not include a license file at import. This private beta copy does not add a license grant for the upstream code or assets.
