# Platform updates from GitHub

MediaHub separates **release discovery** from **host mutation**. The Core checks
only GitHub's fixed API origin for the configured `owner/repository` and
never executes a branch, a raw script URL or release notes.

Public repositories require no credential. A private repository uses a
repository-scoped, read-only GitHub credential entered on the Updates page over
HTTPS. Core stores that value only in the encrypted release secret store and
returns only configured/not-configured state to the browser. The credential is
sent only to `https://api.github.com`; it is never embedded in a URL, event,
response or log.

Use a fine-grained personal access token restricted to this one repository with
**Contents: read**. Do not copy an interactive workstation token or a token with
write, workflow, package-delete or repository-administration permissions into
MediaHub.

Tagging a reviewed commit as `vX.Y.Z` runs the release workflow. It builds Core
and Agent images, publishes immutable GHCR images, creates build attestations and
attaches `mediahub-release.json` plus digest-identified offline image bundles to
the GitHub Release. GitHub's API reports the
asset SHA-256 digest; MediaHub requires that digest before it calls a release
verified.

The offline bundles let a private installation update through the Releases API
using only the same repository-scoped **Contents: read** credential. MediaHub
does not need a broader classic token with package or repository-wide scopes on
the server merely to pull private GHCR images.

The UI can report an available release as soon as the repository is selected in
Settings and, for a private repository, read-only access is saved in Updates.
Installation remains disabled until a host-side transactional updater
is deployed and acceptance-tested. That updater must:

1. download the exact manifest and verify its reported SHA-256 digest;
2. accept only immutable `ghcr.io/...@sha256:...` image references or the
   manifest's exact SHA-256 identified release bundles;
3. create a configuration/database backup without copying media;
4. preserve certificates, encrypted secrets, storage mounts and container limits;
5. start and health-check the new Core before retiring the previous container;
6. keep the previous image/configuration for bounded rollback;
7. never format, move, delete or rewrite media;
8. record a secret-free update result in MediaHub.

This deployment gate is intentional. Merely finding a newer GitHub tag is not
authority for a root-level host change.
