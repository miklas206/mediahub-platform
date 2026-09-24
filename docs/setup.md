# Phase 2 setup

> Historical development instructions, not the current production installer.
> For v0.4.0 HTTPS installation, use [Install MediaHub](install.md).

Core and Agent run independently. Existing services are never imported or executed by Apply.
Keep development bound to loopback. Do not reuse production databases/configuration.

From the checkout, after installing dependencies and building the frontend:

```powershell
.\.venv\Scripts\python.exe -m mediahub.cli agent-init
.\.venv\Scripts\python.exe -m agent.main
```

Keep Agent in its own terminal, then start Core in another:

```powershell
.\.venv\Scripts\python.exe -m mediahub.cli serve
```

Open http://127.0.0.1:18765. Read the installation token privately in a third terminal:

```powershell
.\.venv\Scripts\python.exe -m mediahub.cli bootstrap-token
```

Do not share tokens in chat or screenshots. Create your administrator using a unique password
(at least 12 characters). The token is required once; no default account/password exists.
An existing Phase 1 administrator signs in and still completes the explicit Phase 2 setup.

Wizard: Welcome, System Check, Administrator, Installation Type, Storage, Network, Apps,
Review, Apply, Complete. Authenticated progress persists when continuing or adding storage.
Refresh resumes saved progress. Pre-authentication welcome/check choices are not persisted.
Apply saves configuration and plans, creates only explicitly confirmed new directories,
and marks setup complete. Network changes remain pending until an explicit restart with
`mediahub serve --saved-network`. No automatic broad binding or proxy configuration occurs.

Docker is optional for Core. Missing Agent/Docker produces warnings; storage changes require
Agent, and app previews stay blocked. Real app installation is intentionally unavailable.

To permit new directory creation in the Agent sandbox, explicitly set
`MEDIAHUB_AGENT_CREATE_ENABLED=true` before starting Agent. Default roots are restricted to
`.agent/storage-sandbox`; do not add an existing production media root during this phase.

Verification: `python scripts/qa.py --phase2` uses a separate temporary database and a random
administrator. It tests fresh setup, resume, completion, desktop/mobile dashboard and absence
of the default mock. `python scripts/qa.py` retains the explicit developer mock regression test.
