"""Run real-browser integration tests against an isolated temporary development database."""

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from mediahub.auth import AuthService
from mediahub.config import Config
from mediahub.db import InstallationState, connect, migrate
from mediahub.events import EventBus

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from agent.main import AgentConfig, initialize  # noqa: E402

qa_root = root / ".qa"
qa_root.mkdir(exist_ok=True)
data = Path(tempfile.mkdtemp(prefix="browser-", dir=qa_root))
phase2 = "--phase2" in sys.argv
config = Config(data_dir=data, dev_mode=not phase2, mock_app=not phase2, _env_file=None)
migrate(config.database_url)
engine, sessions = connect(config.database_url)
password = secrets.token_urlsafe(32)
if not phase2:
    AuthService(sessions, config, EventBus(sessions)).create_admin("qa-admin", password)
    with sessions.begin() as db:
        db.add(InstallationState(setup_completed=True, draft={}))
engine.dispose()
env = {
    **os.environ,
    "MEDIAHUB_DATA_DIR": str(data),
    "MEDIAHUB_BASE_URL": "http://127.0.0.1:18766",
    "MEDIAHUB_ALLOWED_ORIGINS": '["http://127.0.0.1:18766"]',
    "MEDIAHUB_QA_USER": "qa-admin",
    "MEDIAHUB_QA_PASSWORD": password,
    "MEDIAHUB_QA_URL": "http://127.0.0.1:18766",
    "MEDIAHUB_SAMPLE_SECONDS": "1",
    "MEDIAHUB_DEV_MODE": str(not phase2).lower(),
    "MEDIAHUB_MOCK_APP": str(not phase2).lower(),
}
agent = None
if phase2:
    state = data / "agent"
    initialize(AgentConfig(state_dir=state, token_file=state / "token", _env_file=None))
    env.update(
        {
            "MEDIAHUB_AGENT_STATE_DIR": str(state),
            "MEDIAHUB_AGENT_TOKEN_FILE": str(state / "token"),
            "MEDIAHUB_AGENT_URL": "http://127.0.0.1:18769",
            "MEDIAHUB_AGENT_PORT": "18769",
            "MEDIAHUB_AGENT_CREATE_ENABLED": "true",
            "MEDIAHUB_AGENT_DEV_MODE": "true",
            "MEDIAHUB_AGENT_FIXTURES": "true",
        }
    )
    agent = subprocess.Popen(
        [sys.executable, "-m", "agent.main"],
        cwd=root,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
server = subprocess.Popen(
    [sys.executable, "-m", "mediahub.cli", "serve", "--port", "18766"],
    cwd=root,
    env=env,
    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
)
try:
    for _ in range(50):
        if server.poll() is not None:
            raise SystemExit("QA server exited before startup")
        try:
            with urlopen("http://127.0.0.1:18766/api/health", timeout=1) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        raise SystemExit("QA server did not start")
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js is required for browser tests")
    runner = root / "frontend/node_modules/@playwright/test/cli.js"
    spec = "setup.spec.ts" if phase2 else "foundation.spec.ts"
    result = subprocess.run([node, str(runner), "test", spec], cwd=root / "frontend", env=env)
    raise SystemExit(result.returncode)
finally:
    if agent is not None:
        agent.terminate()
        try:
            agent.wait(timeout=10)
        except subprocess.TimeoutExpired:
            agent.kill()
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
    # Retain QA database for diagnosis; it is isolated and gitignored. No media is touched.
