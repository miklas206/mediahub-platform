from sqlalchemy import select

from mediahub.db import PendingImport, Setting
from mediahub.errors import DomainError


class ImportPlanner:
    def __init__(self, sessions, agent, apps):
        self.sessions, self.agent, self.apps = sessions, agent, apps

    async def discover(self):
        report = await self.agent.request("GET", "/v1/discovery")
        with self.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == "discovery_snapshot"))
            if row:
                row.value = report
            else:
                db.add(Setting(key="discovery_snapshot", value=report))
            for container in report["containers"]:
                candidates = container.get("candidates", [])
                if candidates and not db.scalar(
                    select(PendingImport).where(PendingImport.source_id == container["id"])
                ):
                    app = candidates[0]["app"]
                    db.add(
                        PendingImport(
                            source_type=report["source"],
                            source_id=container["id"],
                            detected_app=app,
                            target_app="org.mediahub."
                            + ("seedbox" if app in {"vpn", "qbittorrent"} else app),
                            source_paths=[m["source"] for m in container["mounts"]],
                            target_storage_mappings={},
                            status="discovered",
                            findings=[],
                        )
                    )
        return report

    def snapshot(self):
        with self.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == "discovery_snapshot"))
            return row.value if row else {"containers": [], "relationships": [], "source": "none"}

    async def preview(self, selected, mappings=None, ports=None):
        report = self.snapshot()
        by_id = {c["id"]: c for c in report["containers"]}
        if set(selected) - by_id.keys():
            raise DomainError("unknown_import", "Run discovery again; a selected source is missing")
        plans = []
        installed = {a["packageId"] for a in self.apps.list()}
        runtime = await self.agent.status() if selected else {}
        for identifier in selected:
            source = by_id[identifier]
            if not source["candidates"]:
                raise DomainError("unsupported_import", "This container has no known app adapter")
            detected = source["candidates"][0]["app"]
            target = "org.mediahub." + (
                "seedbox" if detected in {"qbittorrent", "vpn"} else detected
            )
            findings = []
            if report["source"] == "fixture":
                findings.append("Synthetic fixture: not a real migration source")
            if not runtime.get("docker", {}).get("available"):
                findings.append("Docker runtime not available")
            if target in installed:
                findings.append("Target app is already installed")
            proposed = (ports or {}).get(identifier, [p["hostPort"] for p in source["ports"]])
            busy = {
                p["hostPort"]
                for c in report["containers"]
                if c["status"] == "running"
                for p in c["ports"]
            }
            if busy.intersection(proposed):
                findings.append(
                    "Port conflict: proposed port is already in use; a later cutover plan is required"
                )
            paths = [m["source"] for m in source["mounts"] if m["source"]]
            targets = (mappings or {}).get(identifier, {})
            if not targets:
                findings.append("Target storage mappings must be reviewed before readiness")
            if (
                sum(
                    1
                    for other in selected
                    if by_id[other]["candidates"]
                    and by_id[other]["candidates"][0]["app"] == detected
                )
                > 1
            ):
                findings.append("Duplicate app candidates require an explicit source choice")
            if len(set(targets.values())) < len(targets):
                findings.append("Storage conflict: multiple mappings target the same path")
            for path in [*paths, *targets.values()]:
                try:
                    checked = await self.agent.request(
                        "POST", "/v1/directories/inspect", {"path": path}
                    )
                    if not checked["exists"] or not checked["readable"]:
                        findings.append("Missing path or read permission: " + path)
                    if (
                        any(m["source"] == path and m["writable"] for m in source["mounts"])
                        and not checked["writable"]
                    ):
                        findings.append("Writable source mount lacks write permission: " + path)
                except DomainError:
                    findings.append("Path cannot be verified within approved agent roots: " + path)
            plans.append(
                {
                    "source_type": report["source"],
                    "source_id": identifier,
                    "detected_app": detected,
                    "source_paths": paths,
                    "target_app": target,
                    "target_storage_mappings": targets,
                    "status": "blocked" if findings else "ready",
                    "findings": findings,
                    "executable": False,
                    "selected": True,
                }
            )
        return plans

    def list(self):
        with self.sessions() as db:
            records = db.scalars(select(PendingImport)).all()
            return [
                {
                    "id": r.id,
                    "source_id": r.source_id,
                    "source_type": r.source_type,
                    "detected_app": r.detected_app,
                    "status": r.status,
                    "findings": r.findings,
                    "source_paths": r.source_paths,
                    "target_app": r.target_app,
                    "target_storage_mappings": r.target_storage_mappings,
                    "executable": False,
                }
                for r in records
            ]
