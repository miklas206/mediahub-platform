"""Opt-in, persisted speed comparisons with bounded server switching."""

import asyncio
import secrets
import time

from agent.install_files import read_json, save_json


def score(sample):
    down, up = sample["downloadMbps"], sample["uploadMbps"]
    return 2 * down * up / (down + up)


def winner(samples, current):
    best = max(samples, key=lambda key: score(samples[key]))
    if current in samples and score(samples[best]) < score(samples[current]) * 1.25:
        return current
    return best


class VPNOptimizer:
    def __init__(self, locations):
        self.locations = locations
        self.running = False
        self.index = 0
        self.total = 1
        self.measuring = False

    def operation(self, inner):
        if not self.running:
            return inner
        fraction = (
            0.95 if self.measuring else min(100, max(0, inner.get("progress", 0))) / 100 * 0.8
        )
        phase = (
            "Measure download and upload"
            if self.measuring
            else inner.get("step") or "Prepare VPN switch"
        )
        label = (
            f"Server {self.index + 1} of {self.total - 1}"
            if self.index < self.total - 1
            else "Restore selected server"
        )
        return {
            "state": "running",
            "progress": round((self.index + fraction) / self.total * 100),
            "step": f"{label}: {phase}",
            "server": inner.get("server"),
        }

    def state(self):
        root, _, _ = self.locations.context()
        path = root / "vpn-optimizer.json"
        return read_json(path) if path.exists() else {}

    def save(self, state):
        root, _, _ = self.locations.context()
        save_json(root / "vpn-optimizer.json", state)

    async def run(self, rows):
        location = self.locations
        state = self.state()
        report = await location.public()
        current = (report.get("current") or {}).get("server")
        baseline = next((r for r in rows if r["id"] == current), None)
        others = [r for r in rows if r["id"] != current]
        candidates = ([baseline] if baseline else []) + secrets.SystemRandom().sample(
            others, min(2 if baseline else 3, len(others))
        )
        self.index, self.total = 0, len(candidates) + 1
        self.running = True
        samples = {}
        active = None
        try:
            for index, server in enumerate(candidates):
                self.index, self.measuring = index, False
                if not await location.apply(server):
                    active = None
                    continue
                active = server["id"]
                try:
                    self.measuring = True
                    sample = await location.control.driver.measure_vpn_speed()
                    # Do not select a fast tunnel whose port cannot be renewed.
                    location.control.driver.forwarding.next_attempt = 0
                    if (await location.control.driver.forwarding.renew())["status"] != "healthy":
                        continue
                    samples[active] = sample
                except Exception:
                    continue
            selected = winner(samples, current) if samples else current
            target = next((r for r in candidates if r["id"] == selected), baseline)
            self.index, self.measuring = len(candidates), False
            restored = target is not None and await location.apply(target)
            state.update(
                samples=samples,
                selected=selected if restored else None,
                message="Measured servers compared; selected connection verified"
                if restored and samples
                else "Speed comparison unavailable; previous connection restored"
                if restored
                else "No connection passed verification; torrents remain stopped",
            )
        finally:
            self.running = False
            state["lastChecked"] = time.time()
            state["nextCheck"] = time.time() + state.get("intervalHours", 6) * 3600
            self.save(state)

    async def poll(self):
        while True:
            await asyncio.sleep(60)
            try:
                state = self.state()
                control = self.locations.control
                if (
                    not state.get("enabled")
                    or not state.get("intervalHours")
                    or time.time() < state.get("nextCheck", 0)
                    or (control.job and not control.job.done())
                    or control.lifecycle.lock.locked()
                    or not control.lifecycle.state["desiredRunning"]
                ):
                    continue
                _, _, provider = self.locations.context()
                rows = [
                    r
                    for r in await provider.servers(control.driver)
                    if r["country"] == state["country"]
                ]
                if rows:
                    control.job = asyncio.create_task(self.run(rows))
                    await asyncio.shield(control.job)
            except Exception:
                # Persist backoff; retain manual controls and last measurements.
                try:
                    state = self.state()
                    state.update(
                        nextCheck=time.time() + 3600,
                        message="Automatic comparison deferred; retrying in one hour",
                    )
                    self.save(state)
                except Exception:
                    pass
