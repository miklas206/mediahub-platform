import asyncio
import base64
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import unquote

import pytest
from mediahub.apps.plex import PlexLibraryCreate, PlexLibraryEdit, PlexLibraryRemove
from mediahub.errors import DomainError

from agent.install_files import read_json, save_json
from agent.plex_libraries import PlexLibraries, revision
from agent.plex_runtime import PlexRuntime


@pytest.fixture
def libraries(tmp_path):
    section = ET.fromstring(
        '<Directory key="1" title="Renamed Films" type="movie" agent="existing-agent" scanner="existing-scanner"><Location path="/media/movies/1"/><Location path="/media/nas/aaaaaaaaaaaaaaaaaaaaaaaa/files/extra"/></Directory>'
    )
    policy = SimpleNamespace(
        mounts=[
            SimpleNamespace(readOnly=True, target=path)
            for path in ["/media/movies/1", "/media/other/1", "/media/nas/" + "a" * 24]
        ]
        + [SimpleNamespace(readOnly=False, target="/config")]
    )
    state = {"sections": [section], "calls": [], "running": True}

    async def request(_policy, path, method="GET", params=None):
        state["calls"].append((path, method, params))
        if path == "/library/sections" and method == "GET":
            result = ET.Element("MediaContainer")
            result.extend(state["sections"])
            return result
        if path.startswith("/services/browse/"):
            folder = base64.b64decode(unquote(path.rsplit("/", 1)[1])).decode()
            result = ET.Element("MediaContainer")
            if folder == "/media/movies/1":
                for child in ["/media/movies/1/new", "/config", "/media/tv/1"]:
                    ET.SubElement(result, "Path", path=child)
                ET.SubElement(result, "File", path=folder + "/not-a-directory.mkv")
            elif folder not in ["/media/movies/1/new", "/media/other/1"]:
                raise DomainError("unavailable", "Synthetic unavailable folder", 503)
            return result
        return ET.Element("Empty")

    control = SimpleNamespace(
        policy=lambda: policy,
        inspect=AsyncMock(side_effect=lambda _: {"State": {"Running": state["running"]}}),
        lock=asyncio.Lock(),
        plex_get=AsyncMock(side_effect=request),
        record=Mock(),
    )
    service = PlexLibraries(SimpleNamespace(control=control, state_dir=tmp_path))
    return service, state, section


def test_inventory_uses_actual_renamed_libraries_and_readonly_mounts(libraries):
    service, state, _ = libraries
    result = asyncio.run(service.inventory())
    assert result["libraries"][0]["name"] == "Renamed Films"
    assert len(result["libraries"][0]["locations"]) == 2
    assert "/config" not in str(result["roots"])
    assert all(call[1] == "GET" for call in state["calls"])


def test_stopped_plex_reports_prerequisite_without_querying_plex(libraries):
    service, state, _ = libraries
    state["running"] = False
    assert not asyncio.run(service.inventory())["available"]
    assert not state["calls"]
    with pytest.raises(DomainError, match="Start Plex"):
        asyncio.run(service.folders("/media/movies/1"))


@pytest.mark.parametrize(
    "path",
    [
        "/config",
        "/media/movies/10",
        "/media/movies/1/../config",
        "/media/movies/1//sub",
        "/media/movies/1/sub/",
        "/media/movies/1/./sub",
        "/media/movies/1/evil\n",
        "http://evil",
        "/media/movies/1\\sub",
    ],
)
def test_browse_cannot_leave_approved_media_mounts(libraries, path):
    service, state, _ = libraries
    with pytest.raises(DomainError):
        asyncio.run(service.folders(path))
    assert not state["calls"]


def test_browse_ignores_files_and_untrusted_returned_paths(libraries):
    service, _, _ = libraries
    result = asyncio.run(service.folders("/media/movies/1"))
    assert result["folders"] == [{"path": "/media/movies/1/new", "name": "new"}]


def test_edit_changes_only_locations_and_preserves_metadata_and_extra_folders(libraries):
    service, state, section = libraries
    paths = [loc.get("path") for loc in section.findall("Location")] + ["/media/movies/1/new"]
    reply = asyncio.run(
        service.edit("1", PlexLibraryEdit(locations=paths, expectedRevision=revision(section)))
    )
    assert reply["mediaPreserved"]
    writes = [call for call in state["calls"] if call[1] != "GET"]
    assert writes == [
        (
            "/library/sections/1",
            "PUT",
            [("agent", "existing-agent"), *[("location", p) for p in paths]],
        )
    ]
    assert not any(call[0].endswith("/refresh") for call in state["calls"])


def test_edit_can_remove_an_unavailable_nas_without_probing_unchanged_folders(libraries):
    service, state, section = libraries
    asyncio.run(
        service.edit(
            "1", PlexLibraryEdit(locations=["/media/movies/1"], expectedRevision=revision(section))
        )
    )
    assert not any(path.startswith("/services/") for path, _, _ in state["calls"])


def test_concurrent_plex_edit_is_not_overwritten(libraries):
    service, state, section = libraries
    old = revision(section)
    ET.SubElement(section, "Location", path="/media/movies/1/external")
    with pytest.raises(DomainError, match="changed elsewhere"):
        asyncio.run(
            service.edit("1", PlexLibraryEdit(locations=["/media/movies/1"], expectedRevision=old))
        )
    assert all(call[1] == "GET" for call in state["calls"])


def test_new_path_requires_a_real_observed_directory(libraries):
    service, state, section = libraries
    with pytest.raises(DomainError, match="unavailable"):
        asyncio.run(
            service.edit(
                "1",
                PlexLibraryEdit(
                    locations=["/media/movies/1/missing"], expectedRevision=revision(section)
                ),
            )
        )
    assert all(call[1] == "GET" for call in state["calls"])


def test_removed_section_is_not_recreated_on_save(libraries):
    service, state, section = libraries
    expected = revision(section)
    state["sections"] = []
    with pytest.raises(DomainError, match="removed"):
        asyncio.run(
            service.edit(
                "1", PlexLibraryEdit(locations=["/media/movies/1"], expectedRevision=expected)
            )
        )
    assert all(call[1] == "GET" for call in state["calls"])


def test_creation_is_explicit_and_duplicate_retry_does_not_create_again(libraries):
    service, state, _ = libraries
    body = PlexLibraryCreate(name="Other videos", kind="other", locations=["/media/other/1"])
    asyncio.run(service.create(body))
    writes = [call for call in state["calls"] if call[1] != "GET"]
    assert writes[0][0:2] == ("/library/sections", "POST")
    state["sections"].append(
        ET.fromstring(
            '<Directory key="2" title="Other videos" agent="tv.plex.agents.none"><Location path="/media/other/1"/></Directory>'
        )
    )
    assert asyncio.run(service.create(body))["existing"]
    assert len([call for call in state["calls"] if call[1] != "GET"]) == 1


def test_library_removal_requires_confirmation_and_never_calls_file_deletion(libraries):
    service, state, section = libraries
    body = PlexLibraryRemove(expectedRevision=revision(section))
    with pytest.raises(DomainError, match="Confirm"):
        asyncio.run(service.remove("1", body))
    body.confirmRemove = True
    asyncio.run(service.remove("1", body))
    assert [call for call in state["calls"] if call[1] != "GET"] == [
        ("/library/sections/1", "DELETE", None)
    ]


@pytest.mark.parametrize("bootstrap", [None, False])
def test_existing_installs_never_restore_removed_libraries_on_restart(tmp_path, bootstrap):
    control = SimpleNamespace(
        lock=asyncio.Lock(), socket="unused", plex_get=AsyncMock(), record=Mock()
    )
    runtime = PlexRuntime(control, None, tmp_path)
    plan = {"libraries": {"other": ["/media/other/1"]}}
    if bootstrap is not None:
        plan["bootstrapLibraries"] = bootstrap
    save_json(tmp_path / "plex-plan.json", plan)
    asyncio.run(runtime.ensure_libraries(SimpleNamespace()))
    assert runtime.libraries_ready
    control.plex_get.assert_not_awaited()


def test_fresh_library_bootstrap_is_persistent_and_respects_later_deletion(tmp_path):
    control = SimpleNamespace(
        lock=asyncio.Lock(),
        socket="unused",
        plex_get=AsyncMock(return_value=ET.Element("MediaContainer")),
        record=Mock(),
    )
    runtime = PlexRuntime(control, None, tmp_path)
    save_json(
        tmp_path / "plex-plan.json",
        {"libraries": {"other": ["/media/other/1"]}, "bootstrapLibraries": True},
    )
    asyncio.run(runtime.ensure_libraries(SimpleNamespace()))
    assert control.plex_get.await_count == 2
    assert read_json(tmp_path / "plex-plan.json")["bootstrapLibraries"] is False
    control.plex_get.reset_mock()
    restarted = PlexRuntime(control, None, tmp_path)
    asyncio.run(restarted.ensure_libraries(SimpleNamespace()))
    control.plex_get.assert_not_awaited()


def test_explicit_removal_cancels_pending_fresh_install_bootstrap(libraries):
    service, _, section = libraries
    path = service.state_dir / "plex-plan.json"
    save_json(path, {"bootstrapLibraries": True, "libraries": {"other": ["/media/other/1"]}})
    asyncio.run(
        service.remove(
            "1", PlexLibraryRemove(expectedRevision=revision(section), confirmRemove=True)
        )
    )
    assert read_json(path)["bootstrapLibraries"] is False


def test_library_api_requires_https_and_csrf(logged_in, monkeypatch):
    from mediahub.db import InstalledApp, Setting

    svc = logged_in.app.state.services
    monkeypatch.setattr(svc.setup, "require_complete", Mock())
    with svc.sessions.begin() as db:
        db.add(
            InstalledApp(
                package_id="org.mediahub.plex",
                name="Plex",
                version="1",
                state="running",
                is_mock=False,
            )
        )
        db.add(
            Setting(
                key="plex_installation", value={"hostId": "local", "installationId": "plex-main"}
            )
        )
    agent = SimpleNamespace(trusted_transport=True, request=AsyncMock(return_value={"saved": True}))
    monkeypatch.setattr(svc.hosts, "client", lambda host: agent)
    body = {"locations": ["/media/movies/1"], "expectedRevision": "a" * 64}
    path = "/api/v1/plex/libraries/1"
    assert logged_in.put(path, json=body).status_code == 403
    response = logged_in.put("https://127.0.0.1:18765" + path, json=body)
    assert response.status_code == 200, response.text
    agent.request.assert_awaited_once_with("PUT", "/v1/plex/libraries/1", body)
    logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.put("https://127.0.0.1:18765" + path, json=body).status_code == 403
