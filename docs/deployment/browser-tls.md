# Direct browser HTTPS (prepared; not deployed)

Browser-to-Core encryption and Core-to-Agent encryption are separate requirements.
The existing restricted internal listener is not a browser credential transport.
Do not enter Seedbox VPN secrets into the current LAN HTTP UI.

The primary listener supports optional `MEDIAHUB_BROWSER_TLS_CERT` and
`MEDIAHUB_BROWSER_TLS_KEY`. Set both, with an HTTPS `MEDIAHUB_BASE_URL` and matching
allowed origins. The existing browser port is reused: no HTTP redirect port,
reverse proxy, public ingress or firewall change is required. The internal listener
retains its enrollment/health-only allowlist and independent TLS configuration.

When enabled, an unreadable or mismatched certificate/key prevents startup; the
server does not fall back to HTTP. HTTPS base URL enables Secure session cookies.
Browser TLS and trusted-proxy configuration are independent; do not trust forwarded
headers merely to make an HTTP request appear encrypted.

## Deployment gate

1. Obtain operator approval for browser address and workstation trust changes.
2. Verify the CA fingerprint using an already authenticated administrative channel.
3. Issue a server-auth leaf with the exact LAN hostname/IP SANs. Reuse the existing
   internal CA only after reviewing its trust scope. Never distribute its private key.
4. Store the leaf private key with least privilege for the Core service; mount it
   read-only. Validate the key/cert pair, SAN, chain and expiry before restart.
5. Import only the verified public CA certificate into the intended Windows user's
   trust store with explicit approval; record its thumbprint for precise removal.
   Trusting a CA is security-sensitive and not equivalent to accepting one website.
6. Configure direct TLS on the existing browser listener; retain the internal
   listener, Agent trust and pairing identity unchanged.
7. Verify browser trust without an interstitial bypass; verify Secure cookies,
   login/CSRF and SSE. Never click through a certificate warning as a substitute.
8. Test certificate expiry/unknown CA/hostname mismatch rejection. Remove temporary
   setup SSH access and verify rejection of a new setup-key login.

Clients without CA trust cannot use this HTTPS address safely until separately
configured. Rollback to HTTP requires disabling credential-entry features first;
never silently downgrade credential transport. No certificate installation, server
deployment, workstation trust change or firewall mutation has been performed by
adding this document and the optional listener support.

## Remaining Phase 4 work

The complete wizard, secure secret submission/storage, fresh provisioning,
transaction ledger, rotation, adoption and genuine fresh-install browser tests
remain required. Optional TLS listener support alone does not implement them and
does not constitute Phase 4 completion.
