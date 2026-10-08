"""Isolated MediaHub browser checks. No real Docker, accounts, email or packages."""
import json
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
workspace = tempfile.TemporaryDirectory(prefix="mediahub-browser-")
os.environ.update({
    "DATA_DIR": str(Path(workspace.name) / "data"),
    "APPS_DIR": str(Path(workspace.name) / "apps"),
    "SECRET_KEY": "isolated-mediahub-browser-secret",
    "REGISTRY_URL": "",
    "PACKAGES_URL": "",
    "FJORDHUB_SRC_DIR": "",
    "FJORDHUB_UPDATER_URL": "",
    "FJORDHUB_MEMORY_RECONCILE": "0",
})

# Even a machine with an active Docker daemon stays untouched.
with patch("docker.from_env", side_effect=RuntimeError("isolated browser fixture")):
    import app as hub

hub.HostStorage.inventory = lambda self: {"available": False, "pools": []}
fixture_apps = []
fixture_states = {}
hub._get_apps = lambda: list(fixture_apps)
hub.docker_mgr.get_status = lambda definition: dict(
    fixture_states.get(definition["id"], {"state": "not_installed"})
)
hub._update_manager.get_all_statuses = lambda apps: {
    definition["id"]: {"state": "up_to_date"} for definition in apps
}
hub._ensure_install_state_for_existing_apps = lambda apps: None
logging.getLogger("werkzeug").setLevel(logging.ERROR)
server = make_server("127.0.0.1", 0, hub.app, threaded=True)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f"http://127.0.0.1:{server.server_port}"
out = ROOT / "test-results"
out.mkdir(exist_ok=True)
page_errors = []


def inspect(page):
    page.wait_for_load_state("networkidle")
    assert "MediaHub" in page.title()


def check_widths(page, name):
    for width in (1440, 390, 320):
        page.set_viewport_size({"width": width, "height": 1000 if width > 500 else 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
            name, width, page.evaluate("document.documentElement.scrollWidth")
        )
        assert page.locator(".app-card .card-actions > *").evaluate_all("""items => items.every(item => {
            const rect = item.getBoundingClientRect();
            if (!rect.width || !rect.height) return true;
            const card = item.closest('.app-card').getBoundingClientRect();
            return rect.left >= card.left && rect.right <= card.right + 1;
        })"""), (name, width, "clipped app actions")
        page.screenshot(path=str(out / f"mediahub-{name}-{width}.png"), full_page=True)


try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        try:
            page.goto(base + "/setup")
            inspect(page)
            expect(page.locator(".auth-brand")).to_have_text("MediaHub Beta")
            for field, value in {
                "username": "Browser Admin", "email": "admin@example.test",
                "password": "Browser-admin-fixture-73!", "password2": "Browser-admin-fixture-73!",
            }.items():
                page.locator("#" + field).fill(value)
            page.get_by_role("button", name="Opret admin-konto").click()
            expect(page.get_by_role("heading", name="Gør MediaHub klar")).to_be_visible()
            inspect(page)
            check_widths(page, "onboarding")
            page.get_by_role("button", name="Spring over", exact=False).click()
            expect(page.get_by_role("heading", name="Lageradgang til dine apps")).to_be_visible()
            page.get_by_role("button", name="Spring over", exact=True).click()
            expect(page).to_have_url(base + "/")
            inspect(page)
            expect(page.locator("#hub-getting-started")).to_be_visible()
            expect(page.locator("#hub-app-summary")).to_have_text("0 installerede apps · 0 kører · 0 værktøjer")
            check_widths(page, "empty")

            fixture_apps.extend([
                {"id": "fixture-media", "name": "Mediebibliotek", "tagline": "Film og serier samlet.",
                 "accent": "#3b82f6", "default_port": 18091, "icon": "camera"},
                {"id": "fixture-files", "name": "Filer og deling", "tagline": "Dine dokumenter og billeder.",
                 "accent": "#10b981", "default_port": 18092, "icon": "share"},
            ])
            fixture_states["fixture-media"] = {"state": "running", "uptime": "2t"}
            fixture_states["fixture-files"] = {"state": "not_installed"}
            tool = hub.package_manager.root / "calendar"
            tool.mkdir()
            (tool / "manifest.json").write_text(json.dumps({"id": "calendar", "version": "2.0.0"}), encoding="utf-8")
            (tool / "body.html").write_text('<p id="fixture-tool-ready">Kalenderen er åbnet i MediaHub.</p>', encoding="utf-8")
            (tool / "styles.css").write_text("/* isolated fixture */", encoding="utf-8")
            (tool / "app.js").write_text("/* isolated fixture */", encoding="utf-8")
            page.reload()
            inspect(page)
            expect(page.locator("#installed-grid #card-fixture-media")).to_be_visible()
            expect(page.locator("#available-grid #card-fixture-files")).to_be_visible()
            expect(page.locator("#card-fixture-files .btn-toggle")).to_have_text("Installer")
            expect(page.locator("#hub-app-summary")).to_have_text("1 installeret app · 1 kører · 1 værktøj")
            expect(page.locator("#hub-tools-section")).to_be_visible()
            expect(page.locator("#hub-getting-started")).not_to_be_visible()
            check_widths(page, "apps")

            page.get_by_role("searchbox").fill("kalender")
            expect(page.locator("#hub-tools-section")).to_be_visible()
            expect(page.locator("#installed-section")).not_to_be_visible()
            expect(page.locator("#available-section")).not_to_be_visible()
            page.get_by_role("searchbox").fill("not-a-real-app")
            expect(page.locator("#hub-search-empty")).to_be_visible()
            page.get_by_role("button", name="Ryd", exact=True).click()
            expect(page.locator("#hub-search-empty")).not_to_be_visible()
            expect(page.locator("#installed-section")).to_be_visible()
            expect(page.get_by_role("searchbox")).to_be_focused()
            page.get_by_role("link", name="Åbn Kalender", exact=True).click()
            expect(page).to_have_url(base + "/packages/calendar")
            expect(page.locator("#fixture-tool-ready")).to_be_visible()
            inspect(page)
            check_widths(page, "tool")

            # Real local authentication + server rendering, restricted to a fixture account.
            member_id = hub._auth.create_user("Browser Member", "Browser-member-fixture-73!")
            hub._auth.set_user_app_access(member_id, "fixture-media", "user")
            member_context = browser.new_context(viewport={"width": 390, "height": 844})
            member = member_context.new_page()
            member.on("pageerror", lambda error: page_errors.append(str(error)))
            member.goto(base + "/login")
            inspect(member)
            member.locator("#username").fill("Browser Member")
            member.locator("#password").fill("Browser-member-fixture-73!")
            member.get_by_role("button", name="Log ind", exact=True).click()
            expect(member).to_have_url(base + "/")
            inspect(member)
            expect(member.locator(".app-card")).to_have_count(1)
            expect(member.locator("#card-fixture-media")).to_be_visible()
            expect(member.get_by_role("link", name="Min konto", exact=True)).to_be_visible()
            for label in ("Indstillinger", "Brugere", "Ressourcer"):
                expect(member.get_by_role("link", name=label, exact=True)).to_have_count(0)
            expect(member.locator(".btn-app-settings")).to_have_count(0)
            for selector in (".btn-toggle", ".btn-delete", ".btn-link-hub", ".card-update-row", "#refresh-btn"):
                expect(member.locator(selector)).not_to_be_visible()
            expect(member.get_by_role("link", name="Åbn Kalender", exact=True)).to_be_visible()
            member.get_by_role("searchbox").fill("Filer")
            expect(member.locator("#hub-search-empty")).to_be_visible()
            expect(member.locator("#card-fixture-files")).to_have_count(0)
            member.get_by_role("button", name="Ryd", exact=True).click()
            restricted_settings = member.request.get(base + "/settings", max_redirects=0)
            assert restricted_settings.status == 302
            assert restricted_settings.headers["location"] == "/"
            assert member.request.post(base + "/api/packages/calendar/install").status == 403
            assert set(member.request.get(base + "/api/apps-status").json()) == {"fixture-media"}
            assert member.request.get(base + "/api/apps-updates").json() == {}
            assert member.request.post(base + "/apps/fixture-media/stop").status == 403
            assert member.request.post(base + "/apps/fixture-files/start").status == 403
            check_widths(member, "member")
            member_context.close()
            assert not page_errors, page_errors
            print("PASS: MediaHub branding/onboarding, empty hub, installed/available apps, search/clear, builtin launcher, member permissions, desktop 1440 and mobile 390/320, zero page errors")
        except Exception:
            page.screenshot(path=str(out / "mediahub-failure.png"), full_page=True)
            raise
        finally:
            browser.close()
finally:
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()
    workspace.cleanup()
