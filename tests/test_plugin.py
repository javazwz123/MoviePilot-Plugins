from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins.v2"))


class PluginBaseStub:
    def __init__(self):
        self.data = {}
        self.config = {}
        self.messages = []

    def save_data(self, key, value):
        self.data[key] = value

    def get_data(self, key):
        return self.data.get(key)

    def update_config(self, config):
        self.config = config

    def post_message(self, **kwargs):
        self.messages.append(kwargs)


def load_plugin_class():
    app = ModuleType("app")
    core = ModuleType("app.core")
    config = ModuleType("app.core.config")
    config.settings = SimpleNamespace(TZ="Asia/Shanghai")
    log = ModuleType("app.log")
    log.logger = logging.getLogger("nodeseeksign-test")
    log.logger.disabled = True
    plugins = ModuleType("app.plugins")
    plugins._PluginBase = PluginBaseStub
    schemas = ModuleType("app.schemas")
    schema_types = ModuleType("app.schemas.types")
    schema_types.NotificationType = SimpleNamespace(SiteMessage="SiteMessage")

    with patch.dict(
        sys.modules,
        {
            "app": app,
            "app.core": core,
            "app.core.config": config,
            "app.log": log,
            "app.plugins": plugins,
            "app.schemas": schemas,
            "app.schemas.types": schema_types,
        },
    ):
        from nodeseeksign import nodeseeksign

    return nodeseeksign


class FakeClient:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def sign(self, _random_choice):
        self.calls += 1
        return dict(self.result)


class PluginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin_class = load_plugin_class()

    def make_plugin(self):
        plugin = self.plugin_class()
        plugin.init_plugin(
            {
                "enabled": True,
                "notify": False,
                "cookie": "session=test-value",
                "max_retries": 0,
            }
        )
        return plugin

    def test_success_is_saved_and_next_scheduled_run_is_deduplicated(self):
        plugin = self.make_plugin()
        client = FakeClient(
            {
                "success": True,
                "already_signed": False,
                "retryable": False,
                "message": "签到成功",
                "gain": 5,
                "rank": 7,
                "total": 100,
            }
        )
        plugin._build_client = lambda: client

        first = plugin.sign()
        second = plugin.sign()

        self.assertTrue(first["success"])
        self.assertTrue(second["already_signed"])
        self.assertEqual(client.calls, 1)
        self.assertEqual(plugin.data["last_sign_date"], plugin._now().strftime("%Y-%m-%d"))
        self.assertEqual(len(plugin.data["sign_history"]), 1)

    def test_failure_does_not_mark_day_complete(self):
        plugin = self.make_plugin()
        client = FakeClient(
            {
                "success": False,
                "retryable": False,
                "message": "temporary failure",
            }
        )
        plugin._build_client = lambda: client

        result = plugin.sign()

        self.assertFalse(result["success"])
        self.assertNotIn("last_sign_date", plugin.data)
        self.assertEqual(plugin.data["sign_history"][0]["status"], "签到失败")

    def test_legacy_timestamp_prevents_duplicate_run(self):
        plugin = self.make_plugin()
        plugin.data["last_sign_date"] = plugin._now().strftime("%Y-%m-%d %H:%M:%S")
        client = FakeClient({"success": True, "message": "unexpected"})
        plugin._build_client = lambda: client

        result = plugin.sign()

        self.assertTrue(result["already_signed"])
        self.assertEqual(client.calls, 0)


if __name__ == "__main__":
    unittest.main()
