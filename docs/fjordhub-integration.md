# FjordHub integration


## Detection and automatic pairing

MediaHub checks known `MEDIAHUB_FJORDHUB_URL` configuration and the latest installer health-verified address. An installation at another address can be found using **Detect existing FjordHub** in Integrations; no token is needed for detection. Detection checks the private origin, `/api/health` and the resources endpoint's Bearer challenge. It never scans a subnet or discovers unknown servers by guessing ports. A detected installation appears under Apps with the official FjordHub logo. Its installed child apps require a valid Access Token and the `docker.resources.read` API capability. Legacy catalog entries are not treated as installed applications. Submenu links open the corresponding card in FjordHub; they do not grant session authentication or control its containers.

New MediaHub-guided installations create an encrypted token reference automatically. Over the existing pinned SSH connection, only its SHA256 verifier and short display prefix are provisioned to the guest. A root-owned systemd timer checks the installed FjordHub AuthService once per minute, waiting for the first real administrator with an active password. It uses the native token creation policy and replaces the generated verifier with the prearranged verifier; the bearer token never enters SSH commands, job logs, the guest bootstrap file or API responses. MediaHub polls the normal read-only resources API. No hidden administrator or administrator password is created.

The timer survives host/container restarts, stops after successful activation, and expires after seven days. Completing first-administrator setup is still required. Tokens have no automatic expiry, are named `MediaHub read-only integration` in FjordHub, and can be revoked there. Revoked tokens are never reactivated by the timer. Disconnecting in MediaHub deletes its encrypted credential. Older or incompatible FjordHub versions and failed bootstrap attempts retain the manual Access Token flow; installation success is reported separately from pairing success. Existing configured or deliberately disconnected integrations are not automatically replaced.

This is an installer-only provisioning operation. Routine discovery, status checks and app polling remain read-only. It does not alter media, shared storage, container data volumes, app credentials or network shares.

Explicit **Detect existing FjordHub** / **Find and reconnect FjordHub** requests reactivate a previously disconnected installation at the verified address without restoring its deleted token. Background discovery still preserves a deliberate disconnect. **Test Connection** only verifies the supplied token; **Save and connect FjordHub** persists it and enables resource polling.
