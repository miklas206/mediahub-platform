import ast
import json
import tomllib
from pathlib import Path


def test_published_and_runtime_versions_match():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    module = ast.parse((root / "backend/mediahub/__init__.py").read_text(encoding="utf-8"))
    versions = [
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
    ]
    frontend = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))["version"]
    assert versions == [project], "Core runtime version must match the update manifest version"
    assert frontend == project
