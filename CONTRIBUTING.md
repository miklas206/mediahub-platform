# Contributing

This is an early development project. Discuss architecture changes in an issue before broad refactors.
Keep Core app-agnostic, secrets backend-only, and runtime integrations behind typed interfaces.
Do not add automatic service discovery or mutation of an existing installation.

Use a feature branch, add tests, run the README validation commands, regenerate changed contracts and
submit a focused pull request. Include migration and rollback implications for database changes.
All new code must be compatible with Apache-2.0. Do not commit credentials, logs, torrent files,
private tracker metadata, personal media names or production configuration.
