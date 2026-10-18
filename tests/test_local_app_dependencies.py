import importlib.util
import json
import sys
import time
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
    monkeypatch.setattr(module, "prepare_host_metrics", lambda *args: None)
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


def test_approved_storage_checks_mount_identity_and_preserves_local_volume(tmp_path, monkeypatch):
    root, source, calls, _ = fixture(tmp_path, monkeypatch)
    media = tmp_path / "media"
    movies = media / "movies"
    movies.mkdir(parents=True)
    marker = media / ".identity"
    marker.write_text("synthetic-volume")
    evidence = tmp_path / "snapshot.json"
    snapshot = {
        "scope": "host-mount-namespace",
        "available": True,
        "observedAt": time.time(),
        "mounts": [{"path": str(media), "source": "synthetic-device", "options": ["rw"]}],
    }
    evidence.write_text(json.dumps(snapshot))
    (root / "agent").mkdir()
    policy = {
        "hostMountSnapshot": str(evidence),
        "requiredMounts": {str(media): "synthetic-device"},
        "storageMarkers": {str(marker): "synthetic-volume"},
        "storage": {
            "movies": {"label": "Movies", "kind": "movies", "path": str(movies)},
            "private": {"label": "App data", "kind": "appdata", "path": str(media)},
        },
    }
    (root / "agent/container-apps.json").write_text(json.dumps(policy))
    path = root / "local-apps/mediaseed/compose.json"
    cfg = json.loads(path.read_text())
    original = {"type": "volume", "source": "downloads", "target": "/downloads"}
    cfg["services"]["app"]["volumes"] = [original.copy()]
    cfg["services"]["qbittorrent"] = {"volumes": [original.copy()]}
    path.write_text(json.dumps(cfg))
    module.provision(root, "192.168.1.50", source)
    actual = json.loads(path.read_text())
    for service in ("app", "qbittorrent"):
        volumes = actual["services"][service]["volumes"]
        assert volumes[0] == original
        assert volumes[1]["source"] == str(movies)
        assert volumes[1]["target"] == "/downloads/media/movies"
        assert volumes[1]["bind"]["create_host_path"] is False
        assert len(volumes) == 2
    vpn = json.loads((root / "local-apps/mediavpn/compose.json").read_text())
    approved = json.loads(vpn["services"]["app"]["environment"]["MEDIAVPN_MEDIASEED_STORAGE"])
    assert len(approved) == 1 and approved[0]["source"] == str(movies)
    count = len(calls)
    marker.write_text("wrong-device")
    with pytest.raises(ValueError, match="marker changed"):
        module.provision(root, "192.168.1.50", source)
    assert len(calls) == count


@pytest.mark.parametrize("legacy", [False, True])
def test_other_storage_is_inherited_only_from_verified_policy(tmp_path, monkeypatch, legacy):
    root, _, _, _ = fixture(tmp_path, monkeypatch)
    media = tmp_path / "media"
    other = media / "other"
    other.mkdir(parents=True)
    marker = media / ".identity"
    marker.write_text("volume")
    evidence = tmp_path / "snapshot.json"
    evidence.write_text(json.dumps({"scope": "host-mount-namespace", "available": True, "observedAt": time.time(), "mounts": [{"path": str(media), "source": "disk", "options": ["rw"]}]}))
    (root / "agent").mkdir(exist_ok=True)
    shared = {"hostMountSnapshot": str(evidence), "requiredMounts": {str(media): "disk"}, "storageMarkers": {str(marker): "volume"}}
    entry = {"other": {"kind": "other", "label": "Other Media", "path": str(other)}}
    policy = root / "agent/container-apps.json"
    policy.write_text(json.dumps({**shared, "storage": {} if legacy else entry}))
    plex = root / "agent/plex-install.json"
    plex.write_text(json.dumps({**shared, "storage": entry}))
    original = policy.read_bytes()
    locations = module.approved_media_storage(root)
    assert locations[0]["path"] == "/downloads/media/other"
    assert locations[0]["source"] == str(other)
    assert module.approved_media_storage(root) == locations
    assert policy.read_bytes() == original  # No runtime policy or media mutation.
    if legacy:
        plex.write_text(json.dumps({**shared, "storageMarkers": {}, "storage": entry}))
        with pytest.raises(ValueError, match="matching approved"):
            module.approved_media_storage(root)


def test_media_storage_rejects_changed_existing_target():
    cfg = {
        "services": {
            "app": {
                "volumes": [
                    {"type": "bind", "source": "/unowned", "target": "/downloads/media/movies"}
                ]
            },
            "qbittorrent": {},
        }
    }
    with pytest.raises(ValueError, match="ownership changed"):
        module.configure_media_storage(
            cfg,
            [
                {
                    "id": "movies",
                    "label": "Movies",
                    "path": "/downloads/media/movies",
                    "source": "/approved",
                }
            ],
        )


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
    assert not any("build" in call for call in calls)
    assert (
        json.loads((root / "local-apps/mediavpn/compose.json").read_text())["services"]["app"][
            "image"
        ]
        == "old-app"
    )
    vpn = json.loads((root / "local-apps/mediavpn/compose.json").read_text())
    assert (
        vpn["services"]["app"]["environment"]["MEDIAVPN_MEDIASEED_PROJECT"] == "mediahub-mediaseed"
    )
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
    other = (root / "local-apps/mediaseed/compose.json").read_bytes()
    staged = root / "data/app-updates/mediavpn/test/source"
    staged.mkdir(parents=True)
    (staged / "Dockerfile").write_text("FROM scratch")
    fail[0] = True
    with pytest.raises(OSError):
        module.provision(
            root,
            "192.168.1.50",
            source,
            app="mediavpn",
            app_source=staged,
            app_commit="a" * 40,
            app_repository="miklas206/mediavpn",
        )
    assert (root / "local-apps/mediaseed/compose.json").read_bytes() == other
    assert path.read_bytes() == previous
    assert any("-d" in call and "app" in call for call in calls)
    assert not (root / "local-apps/source.json").exists()


@pytest.mark.parametrize("kind", ["mediaseed", "mediavpn"])
def test_selected_update_changes_only_its_own_version_and_build(tmp_path, monkeypatch, kind):
    root, source, calls, _ = fixture(tmp_path, monkeypatch)
    other = "mediavpn" if kind == "mediaseed" else "mediaseed"
    previous = (root / "local-apps" / other / "compose.json").read_bytes()
    selected_path = root / "local-apps" / kind / "compose.json"
    selected_cfg = json.loads(selected_path.read_text())
    for service in selected_cfg["services"].values():
        service.pop("build", None)  # Older installs can retain only an image reference.
    selected_path.write_text(json.dumps(selected_cfg))
    staged = root / "data/app-updates" / kind / "test/source"
    staged.mkdir(parents=True)
    (staged / "Dockerfile").write_text("FROM scratch")
    (staged / "pyproject.toml").write_text('[project]\nversion="9.0.0"\n')
    monkeypatch.setattr(module, "prepare_vpn_helpers", lambda *args: None)
    module.provision(
        root,
        "192.168.1.50",
        source,
        app=kind,
        app_source=staged,
        app_commit="a" * 40,
        app_repository="miklas206/" + kind,
    )
    cfg = json.loads((root / "local-apps" / kind / "compose.json").read_text())
    labels = cfg["services"]["app"]["labels"]
    assert labels["org.mediahub.app.version"] == "9.0.0"
    assert labels["org.mediahub.app.commit"] == "a" * 40
    assert cfg["services"]["app"]["image"] == "mediahub-" + kind + ":source-" + "a" * 16
    assert (root / "local-apps" / other / "compose.json").read_bytes() == previous
    assert any("build" in call for call in calls)
    assert not any("mediahub-" + other in call for call in calls)


def test_core_preparation_preserves_installed_version(tmp_path, monkeypatch):
    root, source, _, _ = fixture(tmp_path, monkeypatch)
    for kind in ("mediaseed", "mediavpn"):
        path = root / "local-apps" / kind / "compose.json"
        cfg = json.loads(path.read_text())
        cfg["services"]["app"]["labels"] = {"org.mediahub.app.version": "0.1.0"}
        path.write_text(json.dumps(cfg))
        (source / "bundled" / kind / "pyproject.toml").write_text('[project]\nversion="9.0.0"\n')
    module.provision(root, "192.168.1.50", source)
    for kind in ("mediaseed", "mediavpn"):
        cfg = json.loads((root / "local-apps" / kind / "compose.json").read_text())
        assert cfg["services"]["app"]["labels"]["org.mediahub.app.version"] == "0.1.0"


@pytest.mark.parametrize(
    "existing",
    [
        [],
        ["/dev/net/tun:/dev/net/tun:rw"],
        [{"source": "/dev/net/tun", "target": "/dev/net/tun", "permissions": "rw"}],
    ],
)
def test_vpn_tun_mapping_repairs_existing_compose_without_changing_other_settings(existing):
    cfg = {
        "services": {
            "app": {
                "devices": [*existing, "/dev/dri:/dev/dri:rwm"],
                "environment": {"EXISTING": "keep"},
                "volumes": ["private:/data"],
            }
        }
    }
    module.configure_vpn_tun(cfg)
    module.configure_vpn_tun(cfg)
    app = cfg["services"]["app"]
    assert app["devices"] == [
        "/dev/dri:/dev/dri:rwm",
        {"source": "/dev/net/tun", "target": "/dev/net/tun", "permissions": "rwm"},
    ]
    assert app["environment"] == {"EXISTING": "keep"}
    assert app["volumes"] == ["private:/data"]
    assert not app.get("privileged") and not app.get("cap_add")


def test_vpn_tun_mapping_rejects_foreign_source():
    cfg = {"services": {"app": {"devices": ["/unowned/device:/dev/net/tun:rwm"]}}}
    with pytest.raises(ValueError, match="unexpected source"):
        module.configure_vpn_tun(cfg)


def test_update_backfills_tun_in_saved_compose_and_keeps_stopped_apps_stopped(
    tmp_path, monkeypatch
):
    root, source, calls, _ = fixture(tmp_path, monkeypatch)
    module.provision(root, "192.168.1.50", source)
    cfg = json.loads((root / "local-apps/mediavpn/compose.json").read_text())
    assert cfg["services"]["app"]["devices"] == [
        {"source": "/dev/net/tun", "target": "/dev/net/tun", "permissions": "rwm"}
    ]
    assert not any("up" in args and "-d" in args for args in calls)


def test_fresh_runtime_declares_tun_device_without_extra_capabilities():
    import yaml

    cfg = yaml.safe_load(
        (SCRIPTS.parent / "docker/bundled/mediavpn/compose.runtime.yaml").read_text()
    )
    app = cfg["services"]["app"]
    assert app["devices"] == ["/dev/net/tun:/dev/net/tun:rwm"]
    assert not app.get("privileged") and not app.get("cap_add")


def test_fresh_install_builds_and_labels_both_bootstrap_apps(tmp_path, monkeypatch):
    root, source, calls, _ = fixture(tmp_path, monkeypatch)
    original_run = module.run
    for kind in ("mediaseed", "mediavpn"):
        (root / "local-apps" / kind / "compose.json").unlink()
        (source / "bundled" / kind / "hub-proxy.yaml").write_text("{}")
        (source / "bundled" / kind / "pyproject.toml").write_text('[project]\nversion="1.2.3"\n')

    def run(*args, env=None):
        if "config" in args and "--format" in args:
            project = args[args.index("-p") + 1]
            services = {"app": {"build": {}, "environment": {}}, "sso-proxy": {}}
            if project.endswith("mediaseed"):
                services["client-init"] = {"build": {}}
            return json.dumps({"name": project, "services": services})
        return original_run(*args, env=env)

    monkeypatch.setattr(module, "run", run)
    monkeypatch.setattr(module, "certificate", lambda *args: None)
    monkeypatch.setattr(module, "prepare_vpn_helpers", lambda *args: None)
    module.provision(root, "192.168.1.50", source)
    for kind in ("mediaseed", "mediavpn"):
        cfg = json.loads((root / "local-apps" / kind / "compose.json").read_text())
        assert cfg["services"]["app"]["labels"]["org.mediahub.app.version"] == "1.2.3"
        assert cfg["services"]["app"]["image"].startswith("mediahub-" + kind + ":bundled-")
        assert any("build" in call and "mediahub-" + kind in call for call in calls)
