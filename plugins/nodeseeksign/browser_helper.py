from __future__ import annotations

import logging
import re
from http.cookies import SimpleCookie
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


class NodeSeekBrowserError(RuntimeError):
    """Raised when the browser-backed sign-in flow cannot run."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class NodeSeekBrowserClient:
    BASE_URL = "https://www.nodeseek.com"
    BOARD_URL = f"{BASE_URL}/board"

    _PAGE_SCRIPT = r"""
async (randomChoice) => {
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
    const parseJson = text => {
        try { return JSON.parse(text); } catch { return null; }
    };
    const compactBoard = data => {
        if (!data || typeof data !== "object") return null;
        const record = data.record && typeof data.record === "object"
            ? {
                gain: data.record.gain ?? null,
                created_at: data.record.created_at ?? null
            }
            : null;
        return {
            record,
            order: data.order ?? null,
            total: data.total ?? null
        };
    };
    const getBoard = async () => {
        const response = await fetch("/api/attendance/board?page=1", {
            credentials: "include",
            cache: "no-store",
            headers: { Accept: "application/json" }
        });
        const text = await response.text();
        return {
            ok: response.ok,
            status: response.status,
            data: compactBoard(parseJson(text))
        };
    };

    try {
        for (let index = 0; index < 20 && !window.__config__; index += 1) {
            await sleep(250);
        }
        if (!window.__config__) {
            return {
                code: "PAGE_BLOCKED",
                loggedIn: null,
                message: "NodeSeek 页面未正常加载，可能被挑战页或访问策略拦截"
            };
        }
        if (!window.__config__.user) {
            return {
                code: "AUTH_REQUIRED",
                loggedIn: false,
                message: "未检测到登录用户，Cookie 可能已失效"
            };
        }

        const before = await getBoard();
        if (before.data?.record) {
            return {
                code: "ALREADY_COMPLETED",
                loggedIn: true,
                skippedAlready: true,
                boardStatus: before.status,
                board: before.data
            };
        }

        const signResponse = await fetch(`/api/attendance?random=${Boolean(randomChoice)}`, {
            method: "POST",
            credentials: "include",
            cache: "no-store",
            headers: { Accept: "application/json" }
        });
        const signText = await signResponse.text();
        const signData = parseJson(signText);

        await sleep(300);
        let after = null;
        try { after = await getBoard(); } catch { after = null; }

        return {
            code: "SIGN_RESPONSE",
            loggedIn: true,
            signOk: signResponse.ok,
            signStatus: signResponse.status,
            signData,
            signText: signData ? "" : signText.slice(0, 200),
            boardStatus: after?.status ?? null,
            board: after?.data ?? null
        };
    } catch (error) {
        return {
            code: "BROWSER_REQUEST_ERROR",
            loggedIn: Boolean(window.__config__?.user),
            message: String(error?.message || error || "浏览器请求失败").slice(0, 200)
        };
    }
}
"""

    def __init__(
        self,
        cookie: str,
        *,
        user_agent: str = "",
        use_proxy: bool = False,
        timeout: int = 60,
    ) -> None:
        self._cookie = (cookie or "").strip()
        self._user_agent = (user_agent or "").strip()
        self._use_proxy = bool(use_proxy)
        self._timeout = max(15, min(int(timeout or 60), 180))

    @staticmethod
    def parse_cookie_header(cookie_header: str) -> List[Dict[str, str]]:
        """Parse a Cookie header without logging or persisting its values."""
        source = (cookie_header or "").strip()
        if not source:
            return []

        parsed: Dict[str, str] = {}
        jar = SimpleCookie()
        try:
            jar.load(source)
            parsed = {name: morsel.value for name, morsel in jar.items()}
        except Exception:
            parsed = {}

        if not parsed:
            for item in source.split(";"):
                name, separator, value = item.strip().partition("=")
                if separator and name and not name.startswith("$"):
                    parsed[name] = value

        return [{"name": name, "value": value} for name, value in parsed.items()]

    @staticmethod
    def _clean_message(value: Any, fallback: str = "签到失败") -> str:
        text = str(value or fallback).replace("\x00", " ")
        return re.sub(r"\s+", " ", text).strip()[:240]

    @classmethod
    def normalize_payload(cls, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {
                "success": False,
                "retryable": True,
                "message": "浏览器未返回签到结果",
            }

        code = payload.get("code")
        if code == "PAGE_BLOCKED":
            return {
                "success": False,
                "auth_error": False,
                "retryable": True,
                "message": cls._clean_message(payload.get("message"), "NodeSeek 页面未正常加载"),
            }
        if code == "AUTH_REQUIRED" or payload.get("loggedIn") is False:
            return {
                "success": False,
                "auth_error": True,
                "retryable": False,
                "message": cls._clean_message(payload.get("message"), "Cookie 已失效"),
            }

        sign_data = payload.get("signData") if isinstance(payload.get("signData"), dict) else {}
        board = payload.get("board") if isinstance(payload.get("board"), dict) else {}
        record = board.get("record") if isinstance(board.get("record"), dict) else {}
        signed_now = sign_data.get("success") is True
        confirmed_by_record = bool(record)
        message = cls._clean_message(
            sign_data.get("message") or payload.get("signText") or payload.get("message"),
            "签到成功" if signed_now else "签到请求未成功",
        )
        already_message = bool(
            re.search(r"(?:已经|已).{0,4}签到|签到.{0,4}(?:完成|过)|already.{0,8}(?:sign|check)", message, re.I)
        )

        if signed_now or confirmed_by_record or already_message:
            already_signed = bool(payload.get("skippedAlready")) or (not signed_now and (confirmed_by_record or already_message))
            return {
                "success": True,
                "already_signed": already_signed,
                "retryable": False,
                "message": message if sign_data else ("今日已签到" if already_signed else "签到成功"),
                "gain": sign_data.get("gain", record.get("gain")),
                "current": sign_data.get("current"),
                "rank": board.get("order"),
                "total": board.get("total"),
                "created_at": record.get("created_at"),
                "http_status": payload.get("signStatus") or payload.get("boardStatus"),
            }

        status = payload.get("signStatus") or payload.get("boardStatus")
        auth_error = status == 401
        return {
            "success": False,
            "auth_error": auth_error,
            "retryable": not auth_error,
            "message": message,
            "http_status": status,
        }

    def sign(self, random_choice: bool) -> Dict[str, Any]:
        cookies = self.parse_cookie_header(self._cookie)
        if not cookies:
            return {
                "success": False,
                "auth_error": True,
                "retryable": False,
                "message": "未配置有效 Cookie",
            }

        try:
            from app.core.config import settings
            from cloakbrowser import launch_context
        except Exception as error:
            raise NodeSeekBrowserError("MoviePilot CloakBrowser 运行环境不可用", retryable=False) from error

        launch_options: Dict[str, Any] = {
            "headless": True,
            "humanize": getattr(settings, "CLOAKBROWSER_HUMANIZE", True),
            "human_preset": getattr(settings, "CLOAKBROWSER_HUMAN_PRESET", "default"),
            "viewport": {"width": 1280, "height": 720},
        }
        if self._user_agent:
            launch_options["user_agent"] = self._user_agent
        if self._use_proxy and getattr(settings, "PROXY_SERVER", None):
            launch_options["proxy"] = settings.PROXY_SERVER

        context: Optional[Any] = None
        page: Optional[Any] = None
        try:
            context = launch_context(**launch_options)
            context.add_cookies(
                [
                    {
                        "name": item["name"],
                        "value": item["value"],
                        "url": self.BASE_URL,
                    }
                    for item in cookies
                ]
            )
            page = context.new_page()
            page.set_default_timeout(self._timeout * 1000)
            page.goto(self.BOARD_URL, wait_until="domcontentloaded", timeout=self._timeout * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=min(self._timeout, 20) * 1000)
            except Exception:
                logger.debug("NodeSeek page did not reach networkidle; continuing after DOM load")
            payload = page.evaluate(self._PAGE_SCRIPT, bool(random_choice))
            return self.normalize_payload(payload)
        except NodeSeekBrowserError:
            raise
        except Exception as error:
            logger.error("NodeSeek browser execution failed: %s", type(error).__name__)
            raise NodeSeekBrowserError(f"浏览器执行失败: {type(error).__name__}") from error
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
