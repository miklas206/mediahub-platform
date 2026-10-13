import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "local_dependencies", SCRIPTS / "prepare_local_apps.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(tmp_path, monkeypatch, running=False):
    root, source = tmp_path / "hub", tmp_path / "source"
    root.mkdir()
    (root / "compose.json").write_text(
        '{"name":"mediahub-platform","services":{"core":{"environment":{}}}}'
    )
    (root / "data").mkdir()
    policy = {}
    for kind in ("mediavpn", "mediaseed"):
        folder = root / "local-apps" / kind
        folder.mkdir(parents=True)
        cfg = {
            "name": "mediahub-" + kind,
            "services": {
                "app": {"build": {"context": "/old/source"}, "image": "old-app", "environment": {}}
            },
        }
        if kind == "mediaseed":
            cfg["services"]["client-init"] = {"build": {"context": "/old/source"}}
        (folder / "compose.json").write_text(json.dumps(cfg))
        (source / "bundled" / kind).mkdir(parents=True)
        (source / "bundled" / kind / "Dockerfile").write_text("FROM python:3.12-slim\n")
        policy["org.mediahub." + kind] = {
            "installationId": "synthetic-installation",
            "project": "mediahub-" + kind,
        }
    (root / "data/managed-apps.json").write_text(json.dumps(policy))
    calls = []
    fail = [False]

    def run(*args, env=None):
        args = tuple(map(str, args))
        calls.append(args)
        if args[:3] == ("docker", "ps", "-aq"):
            return "synthetic"
        if args[:2] == ("docker", "inspect"):
            return json.dumps(
                [
                    {
                        "Config": {"Labels": {"com.docker.compose.service": "app"}},
                        "State": {"Running": running},
                    }
                ]
            )
        if fail[0] and "build" in args:
            raise OSError("Synthetic build failure")
        return ""

    monkeypatch.setattr(module, "run", run)
    monkeypatch.setattr(module.os, "chown", lambda *args: None, raising=False)
    monkeypatch.setattr(module, "prepare", lambda *args: None)
    return root, source, calls, fail


@pytest.mark.parametrize("kind,uid", [("mediavpn", 0), ("mediaseed", 1000)])
def test_existing_tls_identity_is_readable_by_its_consumer_without_replacing_keys(
    tmp_path, monkeypatch, kind, uid
):
    folder = tmp_path / kind
    tls = folder / "tls"
    tls.mkdir(parents=True)
    (tls / "cert.pem").write_bytes(b"public certificate sentinel")
    (tls / "key.pem").write_bytes(b"private key sentinel")
    chowns = []
    monkeypatch.setattr(
        module.os,
        "chown",
        lambda path, owner, group: chowns.append((Path(path).name, owner, group)),
        raising=False,
    )
    service = {
        "volumes": [{"type": "bind", "source": str(tls), "target": "/app-tls", "read_only": True}],
        "cap_drop": ["ALL"],
    }
    cfg = {"services": {"sso-proxy" if kind == "mediavpn" else "app": service}}
    module.repair_tls_permissions(folder, cfg)
    assert chowns == [("tls", uid, uid), ("cert.pem", uid, uid), ("key.pem", uid, uid)]
    assert (tls / "key.pem").read_bytes() == b"private key sentinel"
    assert (tls / "cert.pem").read_bytes() == b"public certificate sentinel"
    assert service["cap_drop"] == ["ALL"]
    assert service["volumes"][0]["read_only"] is True
    assert service["labels"]["org.mediahub.tls.identity"].startswith("owner-v1-" + str(uid))


def test_tls_permission_repair_rejects_changed_bind_source(tmp_path):
    folder = tmp_path / "mediavpn"
    cfg = {
        "services": {
            "sso-proxy": {
                "volumes": [{"type": "bind", "source": "/unowned/tls", "target": "/app-tls"}]
            }
        }
    }
    with pytest.raises(ValueError, match="mount ownership changed"):
        module.repair_tls_permissions(folder, cfg)


def test_preparation_helper_change_invalidates_success_marker(tmp_path):
    (tmp_path / "bundled").mkdir()
    (tmp_path / "bundled/source.json").write_text("unchanged app source")
    (tmp_path / "scripts").mkdir()
    helper = tmp_path / "scripts/prepare_local_apps.py"
    helper.write_text("version one")
    previous = module.fingerprint(tmp_path)
    helper.write_text("version two")
    assert previous != module.fingerprint(tmp_path)


@pytest.mark.parametrize("public", [None, "https://hub.example.com"])
def test_browser_login_uses_configured_hub_origin_without_changing_private_api(
    tmp_path, monkeypatch, public
):
    root, source, calls, _ = fixture(tmp_path, monkeypatch)
    env = {"MEDIAHUB_BASE_URL": "https://192.168.1.50:18765"}
    if public:
        env["MEDIAHUB_PUBLIC_URL"] = public
    (root / "compose.json").write_text(
        json.dumps({"name": "mediahub-platform", "services": {"core": {"environment": env}}})
    )
    for kind in ("mediavpn", "mediaseed"):
        path = root / "local-apps" / kind / "compose.json"
        cfg = json.loads(path.read_text())
        cfg["services"]["app"]["environment"][kind.upper() + "_HUB_URL"] = (
            "https://192.168.1.50:18765"
        )
        path.write_text(json.dumps(cfg))
    module.provision(root, "192.168.1.50", source)
    for kind in ("mediavpn", "mediaseed"):
        cfg = json.loads((root / "local-apps" / kind / "compose.json").read_text())
        actual = cfg["services"]["app"]["environment"]
        assert actual[kind.upper() + "_HUB_URL"] == "https://192.168.1.50:18765"
        assert actual[kind.upper() + "_HUB_BROWSER_URL"] == (public or "https://192.168.1.50:18765")
    assert not any("-d" in call for call in calls)
    count = len(calls)
    env["MEDIAHUB_PUBLIC_URL"] = "https://new-hub.example.com"
    (root / "compose.json").write_text(
        json.dumps({"name": "mediahub-platform", "services": {"core": {"environment": env}}})
    )
    module.provision(root, "192.168.1.50", source)
    assert len(calls) > count
    cfg = json.loads((root / "local-apps/mediavpn/compose.json").read_text())
    assert (
        cfg["services"]["app"]["environment"]["MEDIAVPN_HUB_BROWSER_URL"]
        == "https://new-hub.example.com"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://hub.example",
        "https://user:password@hub.example",
        "https://hub.example/path",
        "https://hub.example/?redirect=elsewhere",
        "//hub.example",
    ],
)
def test_browser_login_rejects_invalid_public_origin(url):
    cfg = {"services": {"core": {"environment": {"MEDIAHUB_PUBLIC_URL": url}}}}
    with pytest.raises(ValueError):
        module.hub_browser_origin(cfg, "192.168.1.50")


def test_updates_install_prerequisites_but_do_not_start_stopped_apps(tmp_path, monkeypatch):
    root, source, calls, _ = fixture(tmp_path, monkeypatch)
    media = tmp_path / "existing-movie.mkv"
    media.write_bytes(b"synthetic media sentinel")
    module.provision(root, "192.168.1.50", source)
    assert any("build" in call and "app" in call for call in calls)
    assert not any("-d" in call for call in calls)
    assert all("--volumes" not in call and "down" not in call for call in calls)
    key = root / "local-apps/mediavpn/data/integrations/mediahub.token"
    original = key.read_bytes()
    assert original == (root / "data/app-integration/mediahub-vpn.token").read_bytes()
    assert media.read_bytes() == b"synthetic media sentinel"
    count = len(calls)
    module.provision(root, "192.168.1.50", source)
    assert len(calls) == count and key.read_bytes() == original


def test_failed_build_restores_previous_compose_and_running_intent(tmp_path, monkeypatch):
    root, source, calls, fail = fixture(tmp_path, monkeypatch, running=True)
    path = root / "local-apps/mediavpn/compose.json"
    previous = path.read_bytes()
    fail[0] = True
    with pytest.raises(OSError):
        module.provision(root, "192.168.1.50", source)
    assert path.read_bytes() == previous
    assert any("-d" in call and "app" in call for call in calls)
    assert not (root / "local-apps/source.json").exists()
