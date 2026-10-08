# fjordcopy / MediaHub beta

- This is the independent MediaHub app hub derived from qlerup/fjordhub, not the older mediahub-platform repository.
- Preserve upstream attribution and Git history. Keep user-facing branding as MediaHub; retain FjordHub protocol identifiers used by app manifests, SSO and Docker integration.
- The hub owns its app catalog, authentication, app lifecycle and launcher. App features belong in the individual apps.
- Keep hosts, IP addresses, credentials and storage paths configurable. Never commit live environment files, databases, deploy keys or user data.
- Validate changes with relevant pytest tests and browser checks for affected flows. Use isolated DATA_DIR/APPS_DIR for local checks.
- Deployment is a separate action requiring the user's instruction. The initial request explicitly authorizes installation in the beta LXC only.
- Clearly distinguish edited, tested, pushed, installed and live-verified work. Never change the existing production MediaHub or FjordHub as part of beta work.
