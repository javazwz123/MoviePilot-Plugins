from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryStructureTest(unittest.TestCase):
    def test_manifest_matches_source(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        metadata = package["nodeseeksign"]
        source_path = ROOT / "plugins" / "nodeseeksign" / "__init__.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        versions = []
        for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            for node in class_node.body:
                if not isinstance(node, ast.Assign):
                    continue
                if any(isinstance(target, ast.Name) and target.id == "plugin_version" for target in node.targets):
                    versions.append(ast.literal_eval(node.value))
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
