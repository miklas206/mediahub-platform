import secrets

from mediahub.auth import hasher
from mediahub.db import User
from mediahub.settings import SettingsService


def test_language_is_saved_for_the_authenticated_account(logged_in):
    assert logged_in.get("/api/v1/auth/me").json()["data"]["language"] == "en"
    response = logged_in.put("/api/v1/auth/preferences", json={"language": "da"})
    assert response.status_code == 200
    assert response.json()["data"] == {"language": "da"}
    assert logged_in.get("/api/v1/auth/me").json()["data"]["language"] == "da"

    service = logged_in.app.state.services
    password = secrets.token_urlsafe(24)
    with service.sessions.begin() as db:
        db.add(User(username="second", password_hash=hasher.hash(password)))
    _, second = service.auth.login("second", password, "test")
    assert service.settings.user_preferences(second["id"]).language == "en"
    first_id = logged_in.get("/api/v1/auth/me").json()["data"]["id"]
    assert SettingsService(service.sessions).user_preferences(first_id).language == "da"


def test_preferences_require_authentication_and_csrf(client, logged_in):
    # The fixture shares this client; remove the session to exercise authentication.
    cookie = client.cookies.get("mediahub_session")
    client.cookies.clear()
    assert client.put("/api/v1/auth/preferences", json={"language": "da"}).status_code == 401
    client.cookies.set("mediahub_session", cookie)
    csrf = client.headers.pop("X-MediaHub-CSRF")
    assert client.put("/api/v1/auth/preferences", json={"language": "da"}).status_code == 403
    client.headers["X-MediaHub-CSRF"] = csrf
    assert client.put("/api/v1/auth/preferences", json={"language": "fr"}).status_code == 422
    assert client.put("/api/v1/auth/preferences", json={"language": "da", "userId": "other"}).status_code == 422
