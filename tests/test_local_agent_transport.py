import pytest
from mediahub.config import Config
from pydantic import ValidationError


@pytest.mark.parametrize(
    "url", ["https://agent:18767", "https://localhost:18767", "http://127.0.0.1:18767"]
)
def test_local_agent_supports_validated_https(url):
    assert Config(_env_file=None, agent_url=url).agent_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:18767",
        "https://user:pass@agent:18767",
        "https://agent:18767/path",
        "https://agent:18767?token=not-real",
        "ftp://agent:18767",
    ],
)
def test_local_agent_rejects_untrusted_transport(url):
    with pytest.raises(ValidationError):
        Config(_env_file=None, agent_url=url)
