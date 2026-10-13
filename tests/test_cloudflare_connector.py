from unittest.mock import AsyncMock

from test_cloudflare_management import BASE, TUNNEL, managed  # noqa: F401

# ruff: noqa: F811


def test_local_connector_uses_protected_token_file_and_no_extra_lxc(
    logged_in, managed, monkeypatch, tmp_path
):
    svc, manager, _ = managed
    svc.config.managed_apps_docker_socket = tmp_path / "synthetic.sock"
    monkeypatch.setenv("HOSTNAME", "synthetic-core")
    own = {
        "Image": "sha256:" + "a" * 64,
        "Config": {"Labels": {"com.docker.compose.project": "mediahub-platform"}},
        "Mounts": [
            {"Type": "bind", "Destination": "/data", "Source": "/opt/mediahub/data"},
            {"Type": "bind", "Destination": "/trust", "Source": "/opt/mediahub/trust"},
        ],
    }
    created = []

    async def docker(method, path, missing=False, body=None):
        if path == "/containers/synthetic-core/json":
            return own
        if method == "GET":
            return None
        if path.startswith("/containers/create"):
            created.append(body)
        return {}

    monkeypatch.setattr(svc.managed_apps, "docker", docker)
    monkeypatch.setattr(
        "mediahub.cloudflare_connector.pull_latest",
        AsyncMock(return_value={"Id": "sha256:" + "b" * 64}),
    )
    response = logged_in.post(BASE + "/tunnels/" + TUNNEL + "/install-connector")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["connectors"][TUNNEL]["state"] == "starting"
    assert "connector-private-token" not in response.text
    assert "connector-private-token" not in str(created)
    spec = created[0]
    assert spec["User"] == "10001:10001"
    assert spec["HostConfig"]["Privileged"] is False
    assert spec["HostConfig"]["CapDrop"] == ["ALL"]
    assert "--token-file" in spec["Cmd"]
    assert all(value.endswith(":ro") for value in spec["HostConfig"]["Binds"])
    assert spec["HostConfig"]["RestartPolicy"] == {"Name": "unless-stopped"}
