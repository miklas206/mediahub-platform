import json

import pytest
from mediahub.errors import DomainError
from test_seedbox_plan import paths, spec

from agent.seedbox_install import PrepareSeedbox, SeedboxInstaller, SeedboxPolicy, mount_verified


def test_mount_source_marker_and_local_fallback(tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    (root / ".mediahub-storage-id").write_text("test-marker")
    info = tmp_path / "mountinfo"
    source = "192.168.50.2:/test"
    info.write_text(f"41 20 0:50 / {root} rw - nfs4 {source} rw,hard\n")
    assert mount_verified(str(root), source, "test-marker", info)
    assert not mount_verified(str(root), "192.168.50.2:/production", "test-marker", info)
    info.write_text(f"41 20 8:1 / {root} rw - ext4 /dev/sda1 rw\n")
    assert not mount_verified(str(root), source, "test-marker", info)
    info.write_text("")
    assert not mount_verified(str(root), source, "test-marker", info)


def test_prepare_revalidates_without_download_writes(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    downloads = tmp_path / "downloads"
    runtime = paths().model_copy(
        update={
            "downloads": str(downloads),
            "appdata": str(work / "qbit"),
            "vpnState": str(work / "vpn"),
            "vpnConfig": str(work / "secret.conf"),
            "dnsConfig": str(work / "dns.conf"),
        }
    )
    policy = SeedboxPolicy.model_construct(
        hostId="remote-test",
        downloadsStorageId="test-only",
        workRoot=str(work),
        paths=runtime,
        nfsSource="192.168.50.2:/test",
        storageMarker="test",
    )
    mounted = [True]
    installer = SeedboxInstaller(None, verify_mount=lambda *_: mounted[0])
    installer.policy = lambda: policy
    review = installer.plan(spec())
    request = PrepareSeedbox(installation=spec(), reviewedPlanDigest=review["digest"])
    mounted[0] = False
    with pytest.raises(DomainError, match="storage"):
        installer.prepare(request)
    assert list(work.iterdir()) == [] and not downloads.exists()
    mounted[0] = True
    assert installer.prepare(request)["containersStarted"] is False
    assert not downloads.exists()
    assert json.loads((work / "installation.json").read_text())["state"] == "prepared"
    assert installer.prepare(request)["alreadyPrepared"] is True


def test_unconfigured_agent_does_not_allow_install():
    with pytest.raises(DomainError, match="not enabled"):
        SeedboxInstaller(None).plan(spec())
