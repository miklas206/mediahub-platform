# Internal HTTPS and certificate lifecycle

MediaHub terminates browser HTTPS itself. The local Agent has an independent
HTTPS listener on a private Docker network; it publishes no host port. Remote
Agents use explicitly paired private addresses. No reverse proxy or Cloudflare
is required. Certificate verification is mandatory before credentials are sent.

The Linux installer generates a per-installation RSA-3072 certificate authority
and separate Core/Agent server keys. The CA is valid for ten years; leaf
certificates expire after 90 days. Core SANs include the selected LAN IPv4,
loopback and service name. Agent SANs include its service name and loopback.
Later remote hosts require their own IP/DNS SANs and certificates.

Only the public `trust/ca.pem` belongs on a client. Verify its fingerprint
through a trusted local console before importing it into your user certificate
store. The private authority directory is root-only; private server keys are
0600, readable by their service UID, and mounted read-only into only that service.
Core receives the public CA and the service token, not the Agent secret vault.

## Renewal

Before expiry, generate a fresh server key and CSR on the server. Use the same
validated SANs and `serverAuth` purpose, sign through the protected local CA,
and verify the resulting certificate against `trust/ca.pem`. Stage new files
outside active paths with matching ownership/permissions. Replace the pair
atomically during a short maintenance restart, then verify Core HTTPS and
Core–Agent requests. Keep the previous pair temporarily for rollback. Do not
change DNS/firewalls or bypass TLS verification. Renewal is operator-managed;
automatic ACME renewal is not configured for this private authority.

To rotate the CA, distribute the new **public** CA alongside the old trust root,
issue/redeploy leaves, verify every connection, and only then remove old trust.
Private authority material never needs to leave the server.

Expired, untrusted or name-mismatched certificates cause connections to fail,
not fall back to HTTP. Agent status becomes unavailable. If a leaf/token is
compromised, block/remove the affected pairing, rotate both identity and token,
issue a fresh certificate and pair again. The private deployment does not use an
online CRL/OCSP responder; removing trust/pairing is the revocation mechanism.
