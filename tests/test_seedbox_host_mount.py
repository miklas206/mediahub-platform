import json
import time

from agent.seedbox_install import host_mount_verified


def test_host_mount_rejects_missing_stale_wrong_readonly(tmp_path):
    path = tmp_path / "snapshot.json"
    row = {
        "path": "/data/downloads",
        "filesystem": "nfs4",
        "source": "host:/test",
        "readOnly": False,
    }
    data = {
        "scope": "host-mount-namespace",
        "available": True,
        "observedAt": time.time(),
        "mounts": [row],
    }

    def check(value):
        path.write_text(json.dumps(value))
        return host_mount_verified(path, "/data/downloads", "host:/test")

    assert check(data)
    assert not check(data | {"mounts": []})
    assert not check(data | {"observedAt": time.time() - 31})
    assert not check(data | {"mounts": [row | {"source": "host:/production"}]})
    assert not check(data | {"mounts": [row | {"readOnly": True}]})
    assert not check(data | {"scope": "container"})


def test_explicit_readonly_legacy_mount_requires_readonly(tmp_path):
    path = tmp_path / "snapshot.json"
    row = {"path": "/data/legacy", "filesystem": "nfs4", "source": "host:/legacy", "readOnly": True}
    data = {
        "scope": "host-mount-namespace",
        "available": True,
        "observedAt": time.time(),
        "mounts": [row],
    }
    path.write_text(json.dumps(data))
    assert host_mount_verified(path, row["path"], row["source"], True)
    assert not host_mount_verified(path, row["path"], row["source"])
    data["mounts"][0]["readOnly"] = False
    path.write_text(json.dumps(data))
    assert not host_mount_verified(path, row["path"], row["source"], True)
