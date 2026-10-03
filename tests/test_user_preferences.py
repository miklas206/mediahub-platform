import secrets

import pytest
from mediahub.auth import hasher
from mediahub.contracts import UserPreferences
from mediahub.db import User
from mediahub.settings import SettingsService


def test_language_is_saved_for_the_authenticated_account(logged_in):
    assert logged_in.get("/api/v1/auth/me").json()["data"]["language"] == "en"
    response = logged_in.put("/api/v1/auth/preferences", json={"language": "da"})
    assert response.status_code == 200
    assert response.json()["data"] == {"language": "da", "appearance": None}
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
    assert (
        client.put(
            "/api/v1/auth/preferences", json={"language": "da", "userId": "other"}
        ).status_code
        == 422
    )


APPEARANCE = {
    "accent": "#22ccff",
    "secondary": "#5566dd",
    "background": "#080c16",
    "depth": 40,
}


def test_appearance_saves_for_one_account_and_survives_a_new_service(logged_in):
    user = logged_in.get("/api/v1/auth/me").json()["data"]
    assert user["appearance"] is None
    response = logged_in.put("/api/v1/auth/preferences", json={"appearance": APPEARANCE})
    assert response.status_code == 200
    assert response.json()["data"] == {"language": "en", "appearance": APPEARANCE}
    assert logged_in.get("/api/v1/auth/me").json()["data"]["appearance"] == APPEARANCE
    service = logged_in.app.state.services
    fresh = SettingsService(service.sessions)
    assert fresh.user_preferences(user["id"]).appearance.model_dump() == APPEARANCE

    password = secrets.token_urlsafe(24)
    with service.sessions.begin() as db:
        second = User(username="second-colours", password_hash=hasher.hash(password))
        db.add(second)
        db.flush()
        second_id = second.id
    assert fresh.user_preferences(second_id).appearance is None
    fresh.save_user_preferences(second_id, UserPreferences(language="da"))
    assert fresh.user_preferences(user["id"]).model_dump() == {
        "language": "en",
        "appearance": APPEARANCE,
    }


def test_partial_language_appearance_and_reset_preserve_other_preferences(logged_in):
    response = logged_in.put(
        "/api/v1/auth/preferences", json={"language": "da", "appearance": APPEARANCE}
    )
    assert response.json()["data"] == {"language": "da", "appearance": APPEARANCE}
    assert logged_in.put("/api/v1/auth/preferences", json={"language": "en"}).json()["data"] == {
        "language": "en",
        "appearance": APPEARANCE,
    }
    assert logged_in.put("/api/v1/auth/preferences", json={"language": "da"}).status_code == 200
    changed = {**APPEARANCE, "depth": 100}
    assert logged_in.put("/api/v1/auth/preferences", json={"appearance": changed}).json()[
        "data"
    ] == {
        "language": "da",
        "appearance": changed,
    }
    assert logged_in.put("/api/v1/auth/preferences", json={}).json()["data"] == {
        "language": "da",
        "appearance": changed,
    }
    assert logged_in.put("/api/v1/auth/preferences", json={"appearance": None}).json()["data"] == {
        "language": "da",
        "appearance": None,
    }
    user = logged_in.get("/api/v1/auth/me").json()["data"]
    assert user["language"] == "da" and user["appearance"] is None


def test_saved_appearance_is_returned_after_signing_in_again(logged_in):
    service = logged_in.app.state.services
    password = secrets.token_urlsafe(24)
    with service.sessions.begin() as db:
        account = User(username="appearance-login", password_hash=hasher.hash(password))
        db.add(account)
        db.flush()
        user_id = account.id
    service.settings.save_user_preferences(
        user_id, UserPreferences(language="da", appearance=APPEARANCE)
    )
    logged_in.cookies.clear()
    response = logged_in.post(
        "/api/v1/auth/login", json={"username": "appearance-login", "password": password}
    )
    assert response.status_code == 200
    assert response.json()["data"]["appearance"] == APPEARANCE
    assert response.json()["data"]["language"] == "da"


def test_hex_colours_are_normalized_and_depth_boundaries_are_accepted(logged_in):
    appearance = {
        key: value.upper() if isinstance(value, str) else 0 for key, value in APPEARANCE.items()
    }
    response = logged_in.put("/api/v1/auth/preferences", json={"appearance": appearance})
    assert response.status_code == 200
    assert response.json()["data"]["appearance"] == {**APPEARANCE, "depth": 0}
    response = logged_in.put(
        "/api/v1/auth/preferences", json={"appearance": {**APPEARANCE, "depth": 100}}
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    "field,value",
    [
        ("accent", "#fff"),
        ("accent", "#aabbccdd"),
        ("accent", "#aabbcc; background:url(https://outside.invalid)"),
        ("accent", "var(--danger)"),
        ("accent", "#aabbcc\n"),
        ("secondary", "javascript:alert(1)"),
        ("background", "rgb(0,0,0)"),
        ("background", 123456),
        ("background", None),
        ("depth", True),
        ("depth", False),
        ("depth", "40"),
        ("depth", 40.0),
        ("depth", -1),
        ("depth", 101),
        ("depth", None),
    ],
)
def test_invalid_appearance_is_rejected_without_changing_saved_values(logged_in, field, value):
    assert (
        logged_in.put("/api/v1/auth/preferences", json={"appearance": APPEARANCE}).status_code
        == 200
    )
    response = logged_in.put(
        "/api/v1/auth/preferences", json={"appearance": {**APPEARANCE, field: value}}
    )
    assert response.status_code == 422
    assert logged_in.get("/api/v1/auth/me").json()["data"]["appearance"] == APPEARANCE
    assert "outside.invalid" not in response.text


@pytest.mark.parametrize(
    "appearance",
    [
        {},
        {"accent": "#aabbcc"},
        {**APPEARANCE, "css": "body{}"},
        "#aabbcc",
        True,
    ],
)
def test_appearance_requires_the_exact_complete_contract(logged_in, appearance):
    assert (
        logged_in.put("/api/v1/auth/preferences", json={"appearance": appearance}).status_code
        == 422
    )


def test_appearance_update_requires_authentication_and_csrf(logged_in):
    cookie = logged_in.cookies.get("mediahub_session")
    logged_in.cookies.clear()
    assert (
        logged_in.put("/api/v1/auth/preferences", json={"appearance": APPEARANCE}).status_code
        == 401
    )
    logged_in.cookies.set("mediahub_session", cookie)
    assert (
        logged_in.put(
            "/api/v1/auth/preferences",
            json={"appearance": APPEARANCE},
            headers={"X-MediaHub-CSRF": "invalid"},
        ).status_code
        == 403
    )
