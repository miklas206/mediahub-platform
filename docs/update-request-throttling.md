# Git-based version checks (Core 0.6.32+)

Core, Agent, MediaSeed and MediaVPN discover main-branch versions with Git, without
calling GitHub REST metadata endpoints. This avoids the unauthenticated REST quota
for those version checks. Other upstream app checks and actual source archive
downloads can still use their existing HTTP APIs.

Core and Agent retain an explicitly configured, repository-bound SSH deploy key.
Without that key, version discovery uses Git over verified HTTPS. Independent app
checks use HTTPS and the existing encrypted GitHub token, when present, rather than
reusing Core's scoped SSH key. Public repositories need no token; private repositories
require a token with read access to the selected repository. The existing Updates
credential form continues to manage it. No credentials are migrated or broadened.

HTTPS discovery reads main with ls-remote, fetches its exact commit into a disposable
bare repository, verifies FETCH_HEAD, and reads the reviewed pyproject path with git
show. It never checks out source or runs source hooks. Redirects, external transports,
inherited Git configuration, credential helpers and interactive prompts are disabled;
TLS verification remains enabled. Authentication is passed only through child-process
configuration in the environment, never URLs, argv or on-disk configuration. Git error
output is withheld; a failed check explains the network/Git/repository-access requirements.

Core's metadata service shares HTTPS results for five minutes, keyed by repository,
credential fingerprint and metadata path. Reading metadata also populates the head
cache for MainBranchWatch. Credential changes select a new cache identity. Failures
are reused for 60 seconds to prevent repeated page loads from retrying immediately.
Caches are bounded, and disposable Git data has existing time/size limits.

The new Core image already installs Git and CA certificates, so both a fresh install
and an upgrade obtain prerequisites automatically. The cache directory is created
idempotently in existing persistent Core data. Configuration, credentials, users,
media and app versions are retained. Missing Git produces an explicit requirement
error. Version discovery does not install software or start apps.

The legacy shared REST cache remains available for HTTP discovery consumers. Its
provider cooldown survives Core restarts; source checks never clear that deadline
or rotate credentials to retry a blocked REST request.
