from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryStructureTest(unittest.TestCase):
    def test_v2_fallback_resolves_to_plugins_directory(self):
        plugin_id = "nodeseeksign"
        base_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        v2_package_path = ROOT / "package.v2.json"
        v2_package = json.loads(v2_package_path.read_text(encoding="utf-8")) if v2_package_path.exists() else {}

        package_version = "v2" if plugin_id in v2_package else None
        if package_version is None and base_package.get(plugin_id, {}).get("v2") is True:
            package_version = ""

        self.assertEqual(package_version, "")
        self.assertFalse(v2_package_path.exists())
        self.assertFalse((ROOT / "plugins.v2").exists())
        self.assertTrue((ROOT / "plugins" / plugin_id / "__init__.py").is_file())

    def test_manifest_matches_source(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        plugin_id = "nodeseeksign"
        metadata = package[plugin_id]
        source_path = ROOT / "plugins" / plugin_id.lower() / "__init__.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        versions = []
        class_names = []
        for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            class_names.append(class_node.name)
            for node in class_node.body:
                if not isinstance(node, ast.Assign):
                    continue
                if any(isinstance(target, ast.Name) and target.id == "plugin_version" for target in node.targets):
                    versions.append(ast.literal_eval(node.value))
        self.assertEqual(class_names, [plugin_id])
        self.assertEqual(source_path.parent.name, plugin_id.lower())
        self.assertEqual(versions, [metadata["version"]])
        self.assertTrue(metadata["v2"])
        self.assertTrue(metadata["release"])
        self.assertEqual(metadata["system_version"], ">=2.12.0,<3")

    def test_repository_contains_no_secret_fixture(self):
        forbidden = (
            "gh" + "o_",
            "github" + "_pat_",
            "cf_clearance" + "=",
            "Cookie" + ":",
        )
        for path in ROOT.rglob("*"):
            if (
                not path.is_file()
                or ".git" in path.parts
                or "__pycache__" in path.parts
                or path.suffix in {".pyc", ".png", ".ico"}
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for marker in forbidden:
                self.assertNotIn(marker, text, f"sensitive marker {marker!r} found in {path}")


if __name__ == "__main__":
    unittest.main()
