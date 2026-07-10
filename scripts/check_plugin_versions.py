#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


REQUIRED_FIELDS = {"name", "description", "version", "icon", "author", "level"}


def plugin_version(init_file: Path) -> str | None:
    tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))
    for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for node in class_node.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "plugin_version" for target in node.targets):
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    return None


def plugin_class_names(init_file: Path) -> set[str]:
    tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def plugin_root(package_file: Path) -> Path:
    if package_file.name == "package.v2.json":
        return package_file.parent / "plugins.v2"
    return package_file.parent / "plugins"


def check(package_file: Path) -> list[str]:
    errors: list[str] = []
    package = json.loads(package_file.read_text(encoding="utf-8"))
    if not isinstance(package, dict):
        return [f"{package_file}: 插件索引必须是对象"]

    for plugin_id, metadata in package.items():
        if not isinstance(metadata, dict):
            errors.append(f"{plugin_id}: 元数据必须是对象")
            continue
        missing = sorted(REQUIRED_FIELDS - metadata.keys())
        if missing:
            errors.append(f"{plugin_id}: 缺少字段 {', '.join(missing)}")
        plugin_dir = plugin_root(package_file) / plugin_id.lower()
        init_file = plugin_dir / "__init__.py"
        if not init_file.is_file():
            errors.append(f"{plugin_id}: 缺少 {init_file}")
            continue
        if plugin_id not in plugin_class_names(init_file):
            errors.append(f"{plugin_id}: {init_file} 中缺少同名插件主类")
        source_version = plugin_version(init_file)
        if source_version != str(metadata.get("version") or ""):
            errors.append(
                f"{plugin_id}: package 版本 {metadata.get('version')} 与 plugin_version {source_version} 不一致"
            )
        if package_file.name == "package.json" and metadata.get("v2") is not True:
            errors.append(f"{plugin_id}: V2 兼容插件必须声明 v2=true")
        if metadata.get("release") is not True:
            errors.append(f"{plugin_id}: 自动发布插件必须声明 release=true")
    return errors


def main() -> int:
    paths = [Path(value) for value in sys.argv[1:]] or [Path("package.json")]
    errors = [error for path in paths for error in check(path)]
    if errors:
        print("插件仓库校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    print("插件仓库校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
