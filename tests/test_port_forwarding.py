import asyncio

from agent.port_forwarding import PortForwarding


class Driver:
    def __init__(self):
        self.port = 45000
        self.identity = "verified-vpn"
        self.calls = []
        self.fail = False

    async def port_forward_identity(self):
        return self.identity

    async def request_forwarded_port(self):
        self.calls.append("lease")
        if self.fail:
            raise ValueError("SECRET-MUST-NOT-ESCAPE")
        return {"port": self.port, "remainingSeconds": 60}

    async def allow_forwarded_port(self, port, old):
        self.calls.append(("firewall", port, old))

    async def apply_forwarded_port(self, port):
        self.calls.append(("qbit", port))
        return True


def test_renew_change_expiry_and_secret_safe_failure():
    async def scenario():
        now = [100]
        driver = Driver()
        p = PortForwarding(driver, lambda: now[0], lambda: 1000 + now[0])
        first = await p.renew()
        assert first["status"] == "healthy" and first["lastRenewed"] == 1100
        assert first["listenerVerified"]
        await p.renew()
        assert driver.calls.count("lease") == 1
        now[0] += 31
        driver.port = 46000
        second = await p.renew()
        assert second["currentPort"] == 46000 and second["lastRenewed"] == 1131
        assert ("firewall", 46000, 45000) in driver.calls
        now[0] += 61
        assert p.public()["status"] == "degraded"
        driver.fail = True
        failed = await p.renew()
        assert failed["status"] == "degraded" and failed["lastRenewed"] == 1131
        assert "SECRET" not in str(failed)
        before = len(driver.calls)
        await p.renew()
        assert len(driver.calls) == before

    asyncio.run(scenario())


def test_initial_request_before_client_and_namespace_replacement():
    async def scenario():
        driver = Driver()
        p = PortForwarding(driver)
        assert (await p.renew(apply=False))["status"] == "pending_client"
        assert not any(isinstance(c, tuple) and c[0] == "qbit" for c in driver.calls)
        driver.identity = "different-vpn"
        assert (await p.apply_current())["status"] == "degraded"
        p.invalidate()
        assert p.public()["currentPort"] is None

    asyncio.run(scenario())


def test_missing_listener_does_not_claim_reachable_or_lose_configured_port():
    from agent.port_listener import ListeningPortError

    async def scenario():
        driver = Driver()

        async def failed(port):
            raise ListeningPortError("private details")

        driver.apply_forwarded_port = failed
        state = await PortForwarding(driver).renew()
        assert state["status"] == "degraded"
        assert state["qBittorrentVerified"]
        assert not state["listenerVerified"]
        assert "private details" not in state["lastError"]

    asyncio.run(scenario())
