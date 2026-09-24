# Pytest intentionally injects the imported fixture by its argument name.
# ruff: noqa: F811
from mediahub.db import StorageLocation
from mediahub.setup import Draft, SaveDraft
from test_phase2 import bootstrap, setup_client  # noqa: F401


def test_existing_storage_name_conflict_blocks_before_creation(setup_client):
    client = setup_client
    bootstrap(client)
    svc = client.app.state.services
    existing = client.storage_root / "old"
    existing.mkdir()
    with svc.sessions.begin() as db:
        db.add(StorageLocation(name="Movies", kind="movies", path=str(existing)))
    proposed = client.storage_root / "new"
    state = svc.setup.state()
    svc.setup.save(
        SaveDraft(
            revision=state["revision"],
            draft=Draft(
                storage=[
                    {
                        "name": "Movies",
                        "kind": "movies",
                        "path": str(proposed),
                        "action": "create",
                        "confirmed_path": str(proposed),
                    }
                ]
            ),
        )
    )
    review = client.get("/api/v1/setup/review").json()["data"]
    assert not review["canApply"]
    response = client.post("/api/v1/setup/apply", json={"revision": svc.setup.state()["revision"]})
    assert response.status_code == 400
    assert not proposed.exists()
    assert existing.is_dir()


def test_import_selection_persists_without_execution(setup_client):
    client = setup_client
    bootstrap(client)
    report = client.post("/api/v1/discovery/scan").json()["data"]
    identifier = report["containers"][0]["id"]
    svc = client.app.state.services
    state = svc.setup.state()
    svc.setup.save(
        SaveDraft(revision=state["revision"], draft=Draft(selected_imports=[identifier]))
    )
    records = client.get("/api/v1/imports").json()["data"]
    assert next(r for r in records if r["source_id"] == identifier)["status"] == "selected"
    assert all(not r["executable"] for r in records)
