"""Generate checked-in JSON contracts; no server or production connection."""

import json
from pathlib import Path

from mediahub.apps.manifest import Manifest
from mediahub.main import create_app

root = Path(__file__).resolve().parents[1]
target = root / "packages" / "contracts"
target.mkdir(parents=True, exist_ok=True)
for name, schema in [
    ("app-manifest.schema.json", Manifest.model_json_schema()),
    ("openapi.json", create_app().openapi()),
]:
    (target / name).write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
print("Exported manifest schema and OpenAPI contract")
