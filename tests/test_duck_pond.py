"""Theme preferences and packaging only: no real VPN or torrent operations."""
import importlib.util
from pathlib import Path
import pytest
from pydantic import ValidationError
from mediahub.contracts import AppearancePreferences

PALETTE={"accent":"#f6ce73","secondary":"#9ed8bd","background":"#204c42","depth":52,"style":"duck-pond","mode":"dark","density":"comfortable","reducedMotion":False,"navigation":"sidebar"}

def test_theme_saves_for_current_account_and_keeps_legacy_palettes(logged_in):
    assert logged_in.put('/api/v1/auth/preferences',json={'appearance':PALETTE}).status_code==200
    assert logged_in.get('/api/v1/auth/me').json()['data']['appearance']==PALETTE
    assert logged_in.put('/api/v1/auth/preferences',json={'appearance':{**PALETTE,'style':'untrusted-theme'}}).status_code==422
    legacy={key:PALETTE[key] for key in ('accent','secondary','background','depth')}
    parsed=AppearancePreferences(**legacy)
    assert parsed.style=='classic'
    assert logged_in.put('/api/v1/auth/preferences',json={'appearance':legacy}).status_code==200

@pytest.mark.parametrize('app',['mediaseed','mediavpn'])
def test_bundled_app_accepts_pond_override_but_rejects_arbitrary_content(app):
    path=Path(__file__).resolve().parents[1]/'docker'/'bundled'/app/app/'appearance.py'
    spec=importlib.util.spec_from_file_location('pond_'+app,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.ThemePreference(themeOverride='duck-pond').themeOverride=='duck-pond'
    with pytest.raises(ValidationError):module.ThemePreference(themeOverride='<script>')

@pytest.mark.parametrize('kind',['mediaseed','mediavpn'])
def test_existing_app_preferences_keep_other_users_and_persist_pond(tmp_path,kind):
    from contextlib import contextmanager
    import sqlite3
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    path=Path(__file__).resolve().parents[1]/'docker'/'bundled'/kind/kind/'appearance.py'
    spec=importlib.util.spec_from_file_location('preferences_'+kind,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    @contextmanager
    def database():
        with sqlite3.connect(tmp_path/'old.sqlite') as db:yield db
    with database() as db:
        db.execute('CREATE TABLE hub_theme_preferences (user_id TEXT PRIMARY KEY,theme TEXT NOT NULL)')
        db.execute("INSERT INTO hub_theme_preferences VALUES ('other','classic')")
    def application():
        app=FastAPI();module.install_theme_preferences(app,database,lambda:{'id':'tester'},True);return app
    with TestClient(application()) as client:
        assert client.put('/api/auth/preferences',json={'themeOverride':'duck-pond'}).status_code==200
    with TestClient(application()) as client:
        assert module.theme_override(database,'tester')=='duck-pond'
        assert module.theme_override(database,'other')=='classic'
        assert client.put('/api/auth/preferences',json={'themeOverride':None}).status_code==200
        assert module.theme_override(database,'tester') is None
