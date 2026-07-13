from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "nodeseeksign"
sys.path.insert(0, str(PLUGIN_DIR))

from browser_helper import NodeSeekBrowserClient, NodeSeekBrowserError  # noqa: E402


class FakePage:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False
        self.goto_call = None

    def set_default_timeout(self, timeout):
        self.timeout = timeout

    def goto(self, url, **kwargs):
        self.goto_call = (url, kwargs)

    def wait_for_load_state(self, *_args, **_kwargs):
        return None

    def evaluate(self, script, argument):
        self.script = script
        self.argument = argument
        return self.payload

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, payload):
        self.page = FakePage(payload)
        self.cookies = None
        self.closed = False

    def add_cookies(self, cookies):
        self.cookies = cookies

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class BrowserHelperTest(unittest.TestCase):
    def test_cookie_parser_preserves_equals_in_value(self):
        cookies = NodeSeekBrowserClient.parse_cookie_header("session=abc==; theme=dark")
        self.assertEqual(
            cookies,
            [
                {"name": "session", "value": "abc=="},
                {"name": "theme", "value": "dark"},
            ],
        )

    def test_success_payload(self):
        result = NodeSeekBrowserClient.normalize_payload(
            {
                "code": "SIGN_RESPONSE",
                "loggedIn": True,
                "signStatus": 200,
                "signData": {"success": True, "message": "签到成功", "gain": 5, "current": 100},
                "board": {"record": {"gain": 5}, "order": 9, "total": 120},
            }
        )
        self.assertTrue(result["success"])
        self.assertFalse(result["already_signed"])
        self.assertEqual(result["gain"], 5)
        self.assertEqual(result["rank"], 9)

    def test_success_without_server_message_uses_success_fallback(self):
        result = NodeSeekBrowserClient.normalize_payload(
            {
                "code": "SIGN_RESPONSE",
                "loggedIn": True,
                "signStatus": 200,
                "signData": {"success": True, "gain": 5},
                "board": None,
            }
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "签到成功")

    def test_preflight_record_is_already_signed(self):
        result = NodeSeekBrowserClient.normalize_payload(
            {
                "code": "ALREADY_COMPLETED",
                "loggedIn": True,
                "skippedAlready": True,
                "boardStatus": 200,
                "board": {"record": {"gain": 7}, "order": 3, "total": 88},
            }
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["already_signed"])
        self.assertEqual(result["gain"], 7)

    def test_auth_required_is_not_retryable(self):
        result = NodeSeekBrowserClient.normalize_payload(
            {"code": "AUTH_REQUIRED", "loggedIn": False, "message": "Cookie 已失效"}
        )
        self.assertFalse(result["success"])
        self.assertTrue(result["auth_error"])
        self.assertFalse(result["retryable"])

    def test_blocked_page_is_retryable_and_not_an_auth_error(self):
        result = NodeSeekBrowserClient.normalize_payload(
            {"code": "PAGE_BLOCKED", "loggedIn": None, "message": "challenge"}
        )
        self.assertFalse(result["success"])
        self.assertFalse(result["auth_error"])
        self.assertTrue(result["retryable"])

    def test_browser_unavailable_error_can_disable_retry(self):
        error = NodeSeekBrowserError("unavailable", retryable=False)
        self.assertFalse(error.retryable)

    def test_sign_uses_domain_scoped_context_cookies(self):
        payload = {
            "code": "SIGN_RESPONSE",
            "loggedIn": True,
            "signStatus": 200,
            "signData": {"success": True, "message": "签到成功", "gain": 5},
            "board": {"record": {"gain": 5}, "order": 1, "total": 10},
        }
        context = FakeContext(payload)
        launch_options = {}

        cloakbrowser = ModuleType("cloakbrowser")

        def launch_context(**kwargs):
            launch_options.update(kwargs)
            return context

        cloakbrowser.launch_context = launch_context

        app = ModuleType("app")
        core = ModuleType("app.core")
        config = ModuleType("app.core.config")
        config.settings = SimpleNamespace(
            CLOAKBROWSER_HUMANIZE=True,
            CLOAKBROWSER_HUMAN_PRESET="default",
            PROXY_SERVER={"server": "http://127.0.0.1:7890"},
        )

        with patch.dict(
            sys.modules,
            {
                "app": app,
                "app.core": core,
                "app.core.config": config,
                "cloakbrowser": cloakbrowser,
            },
        ):
            result = NodeSeekBrowserClient(
                "session=secret; " + "cf_clearance" + "=clearance",
                use_proxy=True,
                timeout=60,
            ).sign(random_choice=True)

        self.assertTrue(result["success"])
        self.assertEqual(launch_options["proxy"], {"server": "http://127.0.0.1:7890"})
        self.assertEqual(
            context.cookies,
            [
                {"name": "session", "value": "secret", "url": "https://www.nodeseek.com"},
                {"name": "cf_clearance", "value": "clearance", "url": "https://www.nodeseek.com"},
            ],
        )
        self.assertTrue(context.page.closed)
        self.assertTrue(context.closed)


if __name__ == "__main__":
    unittest.main()
