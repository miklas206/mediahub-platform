from agent.seedbox_status import overall_health


def test_aggregate_never_hides_required_storage_or_vpn_failure():
    checks = [{"name": "vpn", "status": "healthy"}, {"name": "storage", "status": "healthy"}]
    assert overall_health(checks) == "healthy"
    assert overall_health(checks + [{"name": "qbit", "status": "degraded"}]) == "degraded"
    for name in ("storage", "vpn", "required-device"):
        assert overall_health(checks + [{"name": name, "status": "critical"}]) == "critical"
    assert overall_health(checks + [{"name": "device", "status": "unknown"}]) != "healthy"
