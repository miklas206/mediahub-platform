"""Private fork catalogs and self-update destination must remain independent."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from services.remote_registry import fetch_json
from updater_service import app as updater


class BundledCatalogTests(unittest.TestCase):
    def test_local_catalog_does_not_require_github_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            expected = {"schema": "fjordhub-registry/v1", "apps": []}
            path.write_text(json.dumps(expected), encoding="utf-8")
            with patch("services.remote_registry.requests.get") as get:
                self.assertEqual(fetch_json(str(path)), expected)
                get.assert_not_called()

    def test_missing_catalog_is_a_reportable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Could not read catalog"):
                fetch_json(str(Path(directory) / "missing.json"))

    def test_local_catalog_requires_json_object(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                fetch_json(str(path))

    def test_https_catalog_still_fetches_remotely(self):
        response = Mock()
        response.json.return_value = {"apps": []}
        with patch("services.remote_registry.requests.get", return_value=response) as get:
            self.assertEqual(fetch_json("https://example.test/registry.json"), {"apps": []})
            self.assertEqual(get.call_args.args[0], "https://example.test/registry.json")


class SelfUpdateOriginTests(unittest.TestCase):
    def test_private_fork_ssh_origin_is_allowed(self):
        with patch.object(updater, "EXPECTED_REPOSITORY", "miklas206/fjordcopy"), patch.object(updater, "cmd_output", return_value="git@github.com:miklas206/fjordcopy.git"):
            updater.validate_origin()

    def test_upstream_and_similar_host_origins_are_refused(self):
        for origin in (
            "https://github.com/qlerup/fjordhub.git",
            "git@github.com:qlerup/fjordhub.git",
            "https://github.com.example.test/miklas206/fjordcopy.git",
        ):
            with self.subTest(origin=origin), patch.object(updater, "EXPECTED_REPOSITORY", "miklas206/fjordcopy"), patch.object(updater, "cmd_output", return_value=origin):
                with self.assertRaisesRegex(RuntimeError, "update refused"):
                    updater.validate_origin()


if __name__ == "__main__":
    unittest.main()
