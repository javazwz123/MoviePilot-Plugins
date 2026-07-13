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
    def __init__(self, payload, events=None):
        self.payload = payload
        self.closed = False
        self.goto_call = None
        self.events = events

    def set_default_timeout(self, timeout):
        self.timeout = timeout

    def goto(self, url, **kwargs):
        self.goto_call = (url, kwargs)
        if self.events is not None:
            self.events.append("goto")

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
        self.events = []
        self.page = FakePage(payload, self.events)
        self.cookies = None
        self.closed = False

    def add_cookies(self, cookies):
        self.events.append("add_cookies")
        self.cookies = cookies

    def new_page(self):
        self.events.append("new_page")
        return self.page

    def close(self):
        self.closed = True


def patched_browser_modules(launch_context):
    cloakbrowser = ModuleType("cloakbrowser")
    cloakbrowser.launch_context = launch_context

    app = ModuleType("app")
    core = ModuleType("app.core")
    config = ModuleType("app.core.config")
    config.settings = SimpleNamespace(
        CLOAKBROWSER_HUMANIZE=True,
        CLOAKBROWSER_HUMAN_PRESET="default",
        PROXY_SERVER={"server": "http://127.0.0.1:7890"},
    )
    return {
        "app": app,
        "app.core": core,
        "app.core.config": config,
        "cloakbrowser": cloakbrowser,
    }


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

    def test_browser_request_error_is_retryable_and_not_an_auth_error(self):
        result = NodeSeekBrowserClient.normalize_payload(
            {"code": "BROWSER_REQUEST_ERROR", "loggedIn": None, "message": "Failed to fetch"}
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

        def launch_context(**kwargs):
            launch_options.update(kwargs)
            return context

        with patch.dict(
            sys.modules,
            patched_browser_modules(launch_context),
        ):
            result = NodeSeekBrowserClient(
                "session=secret; " + "cf_clearance" + "=clearance",
                use_proxy=True,
                timeout=60,
            ).sign(random_choice=True)

        self.assertTrue(result["success"])
        self.assertEqual(launch_options["proxy"], {"server": "http://127.0.0.1:7890"})
        self.assertEqual(context.events, ["new_page", "goto", "add_cookies"])
        self.assertEqual(context.page.goto_call[0], "https://www.nodeseek.com/")
        self.assertEqual(
            context.cookies,
            [
                {"name": "session", "value": "secret", "url": "https://www.nodeseek.com"},
                {"name": "cf_clearance", "value": "clearance", "url": "https://www.nodeseek.com"},
            ],
        )
        self.assertTrue(context.page.closed)
        self.assertTrue(context.closed)

    def test_navigation_error_keeps_stage_and_is_retryable(self):
        context = FakeContext({})

        def goto(_url, **_kwargs):
            raise RuntimeError("Page.goto: net::ERR_CONNECTION_RESET")

        context.page.goto = goto
        with patch.dict(sys.modules, patched_browser_modules(lambda **_kwargs: context)):
            with self.assertRaises(NodeSeekBrowserError) as raised:
                NodeSeekBrowserClient("session=secret-value").sign(random_choice=False)

        self.assertEqual(
            str(raised.exception),
            "打开 NodeSeek 首页失败: Page.goto: net::ERR_CONNECTION_RESET",
        )
        self.assertTrue(raised.exception.retryable)
        self.assertTrue(context.page.closed)
        self.assertTrue(context.closed)

    def test_browser_install_error_is_not_retryable(self):
        def launch_context(**_kwargs):
            raise RuntimeError("BrowserType.launch: Executable doesn't exist at /cache/chromium")

        with patch.dict(sys.modules, patched_browser_modules(launch_context)):
            with self.assertRaises(NodeSeekBrowserError) as raised:
                NodeSeekBrowserClient("session=secret-value").sign(random_choice=False)

        self.assertIn("启动浏览器失败", str(raised.exception))
        self.assertFalse(raised.exception.retryable)

    def test_error_detail_redacts_cookie_values_and_headers(self):
        context = FakeContext({})
        clearance = "cf_clearance"
        cookie_header = "Cookie" + ":"

        def add_cookies(_cookies):
            raise RuntimeError(
                f"invalid cookie session=secret-value; {clearance}=clearance-value\n"
                f"{cookie_header} session=secret-value; {clearance}=clearance-value"
            )

        context.add_cookies = add_cookies
        with patch.dict(sys.modules, patched_browser_modules(lambda **_kwargs: context)):
            with self.assertRaises(NodeSeekBrowserError) as raised:
                NodeSeekBrowserClient(
                    f"session=secret-value; {clearance}=clearance-value"
                ).sign(random_choice=False)

        message = str(raised.exception)
        self.assertIn("注入 Cookie失败", message)
        self.assertNotIn("secret-value", message)
        self.assertNotIn("clearance-value", message)
        self.assertTrue(raised.exception.retryable)
        self.assertTrue(context.closed)
        self.assertTrue(context.page.closed)


if __name__ == "__main__":
    unittest.main()
