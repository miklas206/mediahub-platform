from mediahub.db import User
from sqlalchemy import select


def test_runtime_mutations_require_administrator(logged_in):
    with logged_in.app.state.services.sessions.begin() as db:
        db.scalar(select(User)).role = "viewer"
    for url, payload in [
        ("/api/v1/apps/example/actions/start", None),
        ("/api/v1/apps/example/uninstall", {"confirmedInstallationId": "example"}),
        ("/api/v1/seedbox/prepare", {}),
        ("/api/v1/seedbox/install", {}),
    ]:
        response = logged_in.post(url, json=payload)
        assert response.status_code == 403
        assert "administrator_required" in response.text
