import argparse
import getpass

from mediahub.config import Config
from mediahub.db import connect, migrate


def main():
    parser = argparse.ArgumentParser(prog="mediahub")
    parser.add_argument(
        "command",
        choices=[
            "serve",
            "migrate",
            "admin",
            "schema",
            "agent-init",
            "bootstrap-token",
            "backup-verify",
            "backup-restore",
        ],
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--saved-network", action="store_true")
    parser.add_argument("--backup-file")
    parser.add_argument("--restore-directory")
    args = parser.parse_args()
    config = Config()
    if args.command in {"backup-verify", "backup-restore"}:
        from pathlib import Path

        from mediahub.backups import LIMIT, restore_new_directory, verified_members

        if not args.backup_file:
            raise SystemExit(
                "Specify --backup-file. Passwords are requested privately, never as command arguments."
            )
        source = Path(args.backup_file)
        if not source.is_file() or source.stat().st_size > LIMIT + 1024 * 1024:
            raise SystemExit("Backup file is missing or exceeds the supported size.")
        payload = source.read_bytes()
        from mediahub import app_backups

        app_archive = payload.startswith(app_backups.MAGIC)
        if app_archive:
            restore_new_directory = app_backups.restore_new_directory
            verified_members = app_backups.verified_members
        password = getpass.getpass("Backup password: ")
        try:
            if args.command == "backup-restore":
                if not args.restore_directory:
                    raise ValueError("Specify a new absolute --restore-directory")
                restore_new_directory(payload, password, Path(args.restore_directory))
                print(
                    "Configuration restored to a new offline directory only. No running app or media was modified. Review storage paths, ownership and deployment trust before applying it."
                )
            else:
                verified_members(payload, password)
                print("Encrypted configuration backup verified. Media files are not included.")
        except Exception:
            raise SystemExit(
                "Backup operation failed. Check the password, archive and new destination. No existing installation was replaced."
            ) from None
        return
    if args.command == "agent-init":
        from agent.main import AgentConfig, initialize

        initialize(AgentConfig())
        print("Agent trust token and private sandbox initialized. Token was not printed.")
        return
    if args.command == "bootstrap-token":
        print("Installation tokens are no longer used. Create your administrator in the setup wizard.")
        return
    if args.command == "serve":
        import asyncio

        from mediahub.main import create_app
        from mediahub.serve import serve

        if args.saved_network:
            from sqlalchemy import select

            from mediahub.db import Setting
            from mediahub.setup import NetworkSettings

            engine, sessions = connect(config.database_url)
            with sessions() as db:
                row = db.scalar(select(Setting).where(Setting.key == "network_pending"))
                if not row:
                    raise SystemExit("No saved network configuration exists")
                network = NetworkSettings.model_validate(row.value)
            engine.dispose()
            args.host, args.port = network.listen_host, network.port
            config = config.model_copy(
                update={
                    "base_url": network.base_url,
                    "allowed_origins": network.allowed_origins,
                    "trusted_proxies": network.trusted_proxies,
                }
            )

        asyncio.run(serve(create_app(config), config, args.host, args.port))
        return
    if args.command == "schema":
        import json

        from mediahub.apps.manifest import Manifest

        print(json.dumps(Manifest.model_json_schema(), indent=2))
        return
    config.data_dir.mkdir(parents=True, exist_ok=True)
    migrate(config.database_url)
    if args.command == "admin":
        from mediahub.auth import AuthService
        from mediahub.errors import DomainError
        from mediahub.events import EventBus

        engine, sessions = connect(config.database_url)
        auth = AuthService(sessions, config, EventBus(sessions))
        try:
            if not auth.needs_setup():
                raise SystemExit("An administrator already exists. No changes made.")
            username = input("Administrator username: ").strip()
            password = getpass.getpass("Password (at least 12 characters): ")
            if password != getpass.getpass("Repeat password: "):
                raise SystemExit("Passwords do not match. No account created.")
            auth.create_admin(username, password)
            print("Administrator created. You can now sign in.")
        except DomainError as error:
            raise SystemExit(error.message) from None
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
