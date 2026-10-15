"""Bounded persistent resource history and conservative human-approved recommendations."""

import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path

GIB = 1024**3
BUCKET = 300
WEEK = 7 * 86400


def allocation_key(snapshot):
    return hashlib.sha256(json.dumps(snapshot["limits"], sort_keys=True).encode()).hexdigest()


def recommendations(samples, limits, now):
    """Use observed bucket peaks; missing samples never become zero usage."""
    result = []
    recent = [row for row in samples if row["time"] >= now - 3600]
    week = [row for row in samples if row["time"] >= now - WEEK]
    for metric, floor, step in [
        ("memoryBytes", 256 * 1024**2, 256 * 1024**2),
        ("cpuCores", 0.25, 0.25),
    ]:
        limit = limits.get(metric)
        if not limit:
            continue  # Unlimited shared capacity is not a per-app allocation.
        if len(recent) >= 10 and recent[-1]["time"] - recent[0]["time"] >= 45 * 60:
            near = [row for row in recent if row[metric] >= limit * 0.9]
            if len(near) >= 3:
                peak = max(row[metric] for row in recent)
                target = math.ceil(max(limit * 1.5, peak * 1.3) / step) * step
                result.append(
                    {
                        "metric": metric,
                        "direction": "increase",
                        "current": limit,
                        "proposed": target,
                        "peak": peak,
                        "windowDays": 1 / 24,
                        "coverage": len(recent) / 12,
                    }
                )
                continue
        if (
            len(week) >= WEEK / BUCKET * 0.8
            and week
            and week[-1]["time"] - week[0]["time"] >= WEEK - 2 * BUCKET
        ):
            peak = max(row[metric] for row in week)
            average = sum(row[metric] for row in week) / len(week)
            # Rare bursts count too. A small average alone cannot justify a reduction.
            if peak <= limit * 0.1 and average <= limit * 0.05:
                target = max(floor, math.ceil(peak * 2 / step) * step)
                if target < limit:
                    result.append(
                        {
                            "metric": metric,
                            "direction": "decrease",
                            "current": limit,
                            "proposed": target,
                            "peak": peak,
                            "windowDays": 7,
                            "coverage": len(week) / (WEEK / BUCKET),
                        }
                    )
    return result


class ResourceHistory:
    def __init__(self, data_dir, clock=time.time):
        self.path, self.clock = Path(data_dir) / "resource-history.sqlite", clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS samples(
                app TEXT NOT NULL, installation TEXT NOT NULL, allocation TEXT NOT NULL,
                bucket INTEGER NOT NULL, ram INTEGER NOT NULL, cpu REAL NOT NULL,
                PRIMARY KEY(app,installation,allocation,bucket));
                CREATE TABLE IF NOT EXISTS preferences(app TEXT PRIMARY KEY, enabled INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS notices(app TEXT PRIMARY KEY, signature TEXT, sent REAL);""")
        self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def enabled(self, package):
        with self.connect() as db:
            row = db.execute("SELECT enabled FROM preferences WHERE app=?", (package,)).fetchone()
        return bool(row[0]) if row else True

    def preference(self, package, enabled):
        with self.connect() as db:
            db.execute(
                "INSERT INTO preferences VALUES(?,?) ON CONFLICT(app) DO UPDATE SET enabled=excluded.enabled",
                (package, int(enabled)),
            )
            if not enabled:
                db.execute("DELETE FROM notices WHERE app=?", (package,))

    def record(self, package, snapshot):
        now = self.clock()
        if (
            not snapshot.get("validSample")
            or not snapshot.get("running")
            or abs(now - snapshot.get("sampledAt", 0)) > 90
        ):
            return
        with self.connect() as db:
            db.execute(
                """INSERT INTO samples VALUES(?,?,?,?,?,?)
                ON CONFLICT(app,installation,allocation,bucket) DO UPDATE SET
                ram=MAX(ram,excluded.ram),cpu=MAX(cpu,excluded.cpu)""",
                (
                    package,
                    snapshot["installationId"],
                    allocation_key(snapshot),
                    int(now // BUCKET) * BUCKET,
                    snapshot["memoryBytes"],
                    snapshot["cpuCores"],
                ),
            )
            db.execute("DELETE FROM samples WHERE bucket<?", (now - 14 * 86400,))
            # Protect small systems even with many disconnected or reinstalled apps.
            db.execute(
                "DELETE FROM samples WHERE rowid IN (SELECT rowid FROM samples ORDER BY bucket DESC LIMIT -1 OFFSET 150000)"
            )

    def decorate(self, package, snapshot):
        now = self.clock()
        with self.connect() as db:
            rows = db.execute(
                "SELECT bucket,ram,cpu FROM samples WHERE app=? AND installation=? AND allocation=? AND bucket>=? ORDER BY bucket",
                (package, snapshot["installationId"], allocation_key(snapshot), now - WEEK),
            ).fetchall()
        samples = [{"time": row[0], "memoryBytes": row[1], "cpuCores": row[2]} for row in rows]
        advice = (
            recommendations(samples, snapshot["limits"], now)
            if self.enabled(package) and snapshot.get("editable") and snapshot.get("validSample")
            else []
        )
        from agent.resource_control import split_limits

        for item in advice:
            if item["metric"] == "memoryBytes" and snapshot.get("components"):
                components = [part["name"] for part in snapshot["components"]]
                while (
                    min(
                        part["memoryBytes"]
                        for part in split_limits(
                            {**snapshot["limits"], "memoryBytes": item["proposed"]}, components
                        ).values()
                    )
                    < 64 * 1024**2
                ):
                    item["proposed"] += 256 * 1024**2
        advice = [
            item
            for item in advice
            if item["direction"] != "decrease" or item["proposed"] < item["current"]
        ]
        for item in advice:
            item["id"] = hashlib.sha256(
                json.dumps(
                    [
                        package,
                        snapshot["installationId"],
                        allocation_key(snapshot),
                        item["metric"],
                        item["proposed"],
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            host = snapshot.get("host", {})
            capacity = host.get(item["metric"])
            item["feasible"] = bool(
                capacity
                and item["proposed"] <= capacity * (0.9 if item["metric"] == "memoryBytes" else 1)
            )
        return {
            **snapshot,
            "recommendationsEnabled": self.enabled(package),
            "recommendations": advice,
            "history": {
                "samples": len(samples),
                "days": (samples[-1]["time"] - samples[0]["time"]) / 86400
                if len(samples) > 1
                else 0,
                "peakMemoryBytes": max((r["memoryBytes"] for r in samples), default=None),
                "peakCpuCores": max((r["cpuCores"] for r in samples), default=None),
            },
        }

    def should_notify(self, package, advice):
        signature = "|".join(sorted(item["id"] for item in advice))
        with self.connect() as db:
            old = db.execute(
                "SELECT signature,sent FROM notices WHERE app=?", (package,)
            ).fetchone()
            if not signature:
                db.execute("DELETE FROM notices WHERE app=?", (package,))
                return False
            if old and old[0] == signature and self.clock() - old[1] < 86400:
                return False
            db.execute(
                "INSERT INTO notices VALUES(?,?,?) ON CONFLICT(app) DO UPDATE SET signature=excluded.signature,sent=excluded.sent",
                (package, signature, self.clock()),
            )
        return True
