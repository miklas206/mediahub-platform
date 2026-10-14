"""Non-destructive lifecycle controls for explicitly owned managed app groups."""

from datetime import datetime

from sqlalchemy import select

from mediahub.db import Event, InstalledApp, Setting
from mediahub.errors import DomainError


def provider(row):
    labels = row.get("Config", {}).get("Labels", {})
    return bool(
        labels.get("org.mediahub.mediavpn.profile")
        and not labels.get("org.mediahub.mediavpn.helper")
    )


def role(row):
    labels = row.get("Config", {}).get("Labels", {})
    return {
        key: value
        for key, value in labels.items()
        if key
        in {
            "com.docker.compose.project",
            "com.docker.compose.service",
            "org.mediahub.mediavpn.owner",
            "org.mediahub.mediavpn.profile",
            "org.mediahub.mediavpn.helper",
            "org.mediahub.mediavpn.seedbox",
        }
    }


async def control(adapter, action):
    if action not in {"start", "stop", "restart"}:
        raise DomainError("unsupported_action", "This runtime action is not supported", 400)
    manager, package = adapter.manager, adapter.package
    key = "app_runtime_control:" + package
    async with manager.lock:
        task = manager.tasks.get(package)
        dependency = getattr(manager.svc, "app_dependencies", None)
        if (task and not task.done()) or (
            dependency and dependency.public().get("state") == "preparing"
        ):
            raise DomainError("app_busy", "Wait for app preparation or removal to finish", 409)
        rows = await manager.containers(package)  # Re-check Docker ownership now.
        app_rows = [
            row
            for row in rows
            if row.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == "app"
        ]
        if len(app_rows) != 1:
            raise DomainError(
                "installation_changed",
                "The owned application container could not be identified",
                409,
            )
        with manager.svc.sessions() as db:
            saved = db.scalar(select(Setting).where(Setting.key == key))
            previous = saved.value if saved else {}
        resume = (
            previous.get("resume", [])
            if previous.get("installationId") == manager.policy[package].installationId
            else []
        )

        def persist(desired, selected):
            value = {
                "installationId": manager.policy[package].installationId,
                "desired": desired,
                "resume": [{"name": row["Name"], "role": role(row)} for row in selected],
            }
            with manager.svc.sessions.begin() as db:
                saved = db.scalar(select(Setting).where(Setting.key == key))
                if saved:
                    saved.value = value
                else:
                    db.add(Setting(key=key, value=value))

        manager.svc.events.record(
            "app.control_started", package, action + " requested for owned app containers"
        )
        try:
            if action in {"stop", "restart"}:
                running = [row for row in rows if row.get("State", {}).get("Running")]
                if running:
                    persist("stopped", running)
                    resume = [{"name": row["Name"], "role": role(row)} for row in running]
                # Stop the controller first so it cannot recreate its helpers.
                ordered = sorted(running, key=lambda row: (row not in app_rows, provider(row)))
                for row in ordered:
                    await manager.docker("POST", "/containers/" + row["Id"] + "/stop?t=20")
            if action in {"start", "restart"}:
                rows = await manager.containers(package)
                if resume:
                    selected = [
                        row
                        for row in rows
                        if any(
                            item["name"] == row["Name"] and item["role"] == role(row)
                            for item in resume
                        )
                    ]
                    selected = list(
                        {
                            row["Id"]: row
                            for row in [
                                *selected,
                                *[r for r in rows if r["Id"] == app_rows[0]["Id"]],
                            ]
                        }.values()
                    )
                else:
                    clone = any(
                        role(row).get("org.mediahub.mediavpn.seedbox") == "mediaseed"
                        for row in rows
                    )
                    selected = [
                        row
                        for row in rows
                        if role(row).get("com.docker.compose.service") == "app"
                        or role(row).get("org.mediahub.mediavpn.seedbox") == "mediaseed"
                        or (
                            not clone
                            and role(row).get("com.docker.compose.service") == "qbittorrent"
                        )
                    ]
                # Start providers before consumers; the controller comes last.
                selected.sort(
                    key=lambda row: (
                        not provider(row),
                        role(row).get("com.docker.compose.service") == "app",
                    )
                )
                for row in selected:
                    if not row.get("State", {}).get("Running"):
                        await manager.docker("POST", "/containers/" + row["Id"] + "/start")
                persist("running", selected)
            state = "stopped" if action == "stop" else "running"
            with manager.svc.sessions.begin() as db:
                for app in db.scalars(
                    select(InstalledApp).where(
                        InstalledApp.package_id == package, InstalledApp.state != "uninstalled"
                    )
                ):
                    app.state = state
            manager.svc.events.record(
                "app.control_completed",
                package,
                action + " completed; app configuration and media preserved",
            )
            return state
        except DomainError:
            manager.svc.events.record(
                "app.control_failed",
                package,
                action + " failed; review app status before retrying",
                severity="warning",
            )
            raise
        finally:
            adapter._observations = None


def logs(adapter):
    # Managed runtimes may have Docker log retention disabled. Expose genuine
    # recorded lifecycle events rather than inventing an application log stream.
    with adapter.manager.svc.sessions() as db:
        rows = db.scalars(
            select(Event)
            .where(
                Event.source == adapter.package,
                Event.type.in_(
                    ["app.control_started", "app.control_completed", "app.control_failed"]
                ),
            )
            .order_by(Event.created_at.desc())
            .limit(100)
        ).all()
        return {
            "entries": [
                {
                    "timestamp": datetime.fromisoformat(row.created_at).timestamp(),
                    "hostId": "local",
                    "app": adapter.package,
                    "severity": row.severity,
                    "type": row.type,
                    "message": row.message,
                }
                for row in rows
            ]
        }
