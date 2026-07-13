from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType

from .browser_helper import NodeSeekBrowserClient, NodeSeekBrowserError


BEIJING_TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")


class nodeseeksign(_PluginBase):
    """NodeSeek daily check-in plugin using MoviePilot's browser runtime."""

    # Keep the historical lowercase ID so existing MoviePilot configuration and data remain valid.
    plugin_name = "NodeSeek论坛签到"
    plugin_desc = "使用 CloakBrowser 在真实浏览器上下文中完成 NodeSeek 每日签到"
    plugin_icon = "https://raw.githubusercontent.com/javazwz123/MoviePilot-Plugins/main/icons/nodeseeksign.png"
    plugin_version = "3.0.3"
    plugin_author = "javazwz123"
    author_url = "https://github.com/javazwz123"
    plugin_config_prefix = "nodeseeksign_"
    plugin_order = 10
    auth_level = 2

    _enabled = False
    _notify = True
    _onlyonce = False
    _cookie = ""
    _cron = "0 8 * * *"
    _random_choice = True
    _use_proxy = False
    _user_agent = ""
    _browser_timeout = 60
    _max_retries = 1
    _retry_interval = 30
    _history_days = 30
    _clear_history = False
    _scheduler: Optional[threading.Timer] = None
    _run_lock: Optional[threading.Lock] = None

    _DEFAULT_CONFIG = {
        "enabled": False,
        "notify": True,
        "onlyonce": False,
        "cookie": "",
        "cron": "0 8 * * *",
        "random_choice": True,
        "use_proxy": False,
        "user_agent": "",
        "browser_timeout": 60,
        "max_retries": 1,
        "retry_interval": 30,
        "history_days": 30,
        "clear_history": False,
    }

    @staticmethod
    def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(int(value), maximum))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _now() -> datetime:
        return datetime.now(BEIJING_TIMEZONE)

    def init_plugin(self, config: dict = None):
        self.stop_service()
        if self._run_lock is None:
            self._run_lock = threading.Lock()

        values = {**self._DEFAULT_CONFIG, **(config or {})}
        self._enabled = bool(values.get("enabled"))
        self._notify = bool(values.get("notify"))
        self._onlyonce = bool(values.get("onlyonce"))
        self._cookie = str(values.get("cookie") or "").strip()
        self._cron = str(values.get("cron") or self._DEFAULT_CONFIG["cron"]).strip()
        self._random_choice = bool(values.get("random_choice"))
        self._use_proxy = bool(values.get("use_proxy"))
        self._user_agent = str(values.get("user_agent") or "").strip()
        self._browser_timeout = self._safe_int(values.get("browser_timeout"), 60, 15, 180)
        self._max_retries = self._safe_int(values.get("max_retries"), 1, 0, 3)
        self._retry_interval = self._safe_int(values.get("retry_interval"), 30, 5, 600)
        self._history_days = self._safe_int(values.get("history_days"), 30, 1, 365)
        self._clear_history = bool(values.get("clear_history"))

        config_needs_save = False
        if self._clear_history:
            self.save_data("sign_history", [])
            self.save_data("last_sign_date", "")
            self._clear_history = False
            config_needs_save = True
            logger.info("NodeSeek签到历史已清除")

        run_once = self._onlyonce
        if run_once:
            self._onlyonce = False
            config_needs_save = True

        if config_needs_save:
            self._save_config()

        if run_once:
            self._scheduler = threading.Timer(3.0, self.sign, kwargs={"force": True})
            self._scheduler.daemon = True
            self._scheduler.start()

        logger.info(
            "NodeSeek签到插件初始化：enabled=%s, cron=%s, random=%s, proxy=%s",
            self._enabled,
            self._cron,
            self._random_choice,
            self._use_proxy,
        )

    def _save_config(self) -> None:
        self.update_config(
            {
                "enabled": self._enabled,
                "notify": self._notify,
                "onlyonce": False,
                "cookie": self._cookie,
                "cron": self._cron,
                "random_choice": self._random_choice,
                "use_proxy": self._use_proxy,
                "user_agent": self._user_agent,
                "browser_timeout": self._browser_timeout,
                "max_retries": self._max_retries,
                "retry_interval": self._retry_interval,
                "history_days": self._history_days,
                "clear_history": False,
            }
        )

    def _already_completed_today(self) -> bool:
        today = self._now().strftime("%Y-%m-%d")
        last_sign_date = str(self.get_data("last_sign_date") or "")
        if last_sign_date.startswith(today):
            return True

        history = self.get_data("sign_history") or []
        if not isinstance(history, list):
            return False
        return any(
            isinstance(item, dict)
            and str(item.get("date") or "").startswith(today)
            and (
                str(item.get("status") or "").startswith("已签到")
                or str(item.get("status") or "") == "签到成功"
            )
            for item in history
        )

    def _build_client(self) -> NodeSeekBrowserClient:
        return NodeSeekBrowserClient(
            self._cookie,
            user_agent=self._user_agent,
            use_proxy=self._use_proxy,
            timeout=self._browser_timeout,
        )

    def sign(self, force: bool = False) -> Dict[str, Any]:
        if self._run_lock is None:
            self._run_lock = threading.Lock()
        if not self._run_lock.acquire(blocking=False):
            logger.warning("NodeSeek签到任务已在运行，本次触发已跳过")
            return {"success": False, "message": "签到任务正在运行"}

        try:
            if not force and self._already_completed_today():
                logger.info("NodeSeek今日已完成签到，跳过重复任务")
                return {"success": True, "already_signed": True, "message": "今日已签到"}

            if not self._cookie:
                result = {
                    "success": False,
                    "auth_error": True,
                    "retryable": False,
                    "message": "未配置 Cookie",
                }
                self._finish_run(result)
                return result

            result: Dict[str, Any] = {
                "success": False,
                "retryable": True,
                "message": "签到尚未执行",
            }
            attempts = self._max_retries + 1
            for attempt in range(1, attempts + 1):
                try:
                    logger.info("NodeSeek浏览器签到开始（第 %s/%s 次）", attempt, attempts)
                    result = self._build_client().sign(self._random_choice)
                except NodeSeekBrowserError as error:
                    result = {
                        "success": False,
                        "retryable": error.retryable,
                        "message": str(error),
                    }
                except Exception as error:
                    logger.error("NodeSeek签到出现未预期错误: %s", type(error).__name__)
                    result = {
                        "success": False,
                        "retryable": True,
                        "message": f"签到执行异常: {type(error).__name__}",
                    }

                if result.get("success") or result.get("auth_error") or not result.get("retryable", True):
                    break
                if attempt < attempts:
                    logger.warning("NodeSeek签到失败，%s 秒后重试：%s", self._retry_interval, result.get("message"))
                    time.sleep(self._retry_interval)

            self._finish_run(result)
            return result
        finally:
            self._run_lock.release()

    def _finish_run(self, result: Dict[str, Any]) -> None:
        now = self._now()
        success = bool(result.get("success"))
        already_signed = bool(result.get("already_signed"))
        status = "已签到" if already_signed else ("签到成功" if success else "签到失败")
        entry = {
            "date": now.isoformat(timespec="seconds"),
            "status": status,
            "message": str(result.get("message") or status)[:240],
            "gain": result.get("gain"),
            "current": result.get("current"),
            "rank": result.get("rank"),
            "total": result.get("total"),
        }
        self._save_history(entry)

        if success:
            self.save_data("last_sign_date", now.strftime("%Y-%m-%d"))
            logger.info(
                "NodeSeek签到完成：status=%s, gain=%s, rank=%s",
                status,
                result.get("gain"),
                result.get("rank"),
            )
        else:
            logger.error("NodeSeek签到失败：%s", result.get("message"))

        if self._notify:
            self._send_notification(entry, success)

    @staticmethod
    def _parse_history_time(value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=BEIJING_TIMEZONE)
            return parsed
        except ValueError:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                return parsed.replace(tzinfo=BEIJING_TIMEZONE)
            except ValueError:
                return None

    def _save_history(self, entry: Dict[str, Any]) -> None:
        history = self.get_data("sign_history") or []
        if not isinstance(history, list):
            history = []
        history.append(entry)
        cutoff = self._now() - timedelta(days=self._history_days)
        retained = []
        for item in history:
            if not isinstance(item, dict):
                continue
            item_time = self._parse_history_time(str(item.get("date") or ""))
            if item_time is None or item_time >= cutoff:
                retained.append(item)
        self.save_data("sign_history", retained[-200:])

    def _send_notification(self, entry: Dict[str, Any], success: bool) -> None:
        details = [entry["message"]]
        if entry.get("gain") is not None:
            details.append(f"奖励：{entry['gain']} 鸡腿")
        if entry.get("current") is not None:
            details.append(f"余额：{entry['current']} 鸡腿")
        if entry.get("rank") is not None:
            rank_text = f"排名：第 {entry['rank']} 名"
            if entry.get("total") is not None:
                rank_text += f" / 共 {entry['total']} 人"
            details.append(rank_text)
        self.post_message(
            mtype=NotificationType.SiteMessage,
            title="【NodeSeek论坛签到成功】" if success else "【NodeSeek论坛签到失败】",
            text="\n".join(details),
        )

    def get_state(self) -> bool:
        return self._enabled

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return []
        try:
            from apscheduler.triggers.cron import CronTrigger

            trigger = CronTrigger.from_crontab(self._cron, timezone=settings.TZ)
        except (ImportError, TypeError, ValueError) as error:
            logger.error("NodeSeek签到 Cron 表达式无效：%s", error)
            return []
        return [
            {
                "id": "nodeseeksign",
                "name": "NodeSeek论坛签到",
                "trigger": trigger,
                "func": self.sign,
                "kwargs": {},
            }
        ]

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            self._switch_col("enabled", "启用插件"),
                            self._switch_col("notify", "签到通知"),
                            self._switch_col("random_choice", "随机奖励"),
                            self._switch_col("use_proxy", "使用系统代理"),
                            self._switch_col("onlyonce", "立即运行一次"),
                            self._switch_col("clear_history", "清除历史记录"),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cookie",
                                            "label": "NodeSeek Cookie",
                                            "type": "password",
                                            "clearable": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "user_agent",
                                            "label": "User-Agent（可选，与 Cookie 来源浏览器保持一致）",
                                            "clearable": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._field_col("cron", "签到周期", component="VCronField"),
                            self._field_col("browser_timeout", "浏览器超时（秒）", field_type="number"),
                            self._field_col("max_retries", "失败重试次数", field_type="number"),
                            self._field_col("retry_interval", "重试间隔（秒）", field_type="number"),
                            self._field_col("history_days", "历史保留天数", field_type="number"),
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "warning",
                            "variant": "tonal",
                            "text": "Cookie 属于登录凭证，请仅保存在自己的 MoviePilot 中，不要上传到日志、截图或公开仓库。",
                        },
                    },
                ],
            }
        ], dict(self._DEFAULT_CONFIG)

    @staticmethod
    def _switch_col(model: str, label: str) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "sm": 6, "md": 4},
            "content": [
                {
                    "component": "VSwitch",
                    "props": {"model": model, "label": label},
                }
            ],
        }

    @staticmethod
    def _field_col(
        model: str,
        label: str,
        *,
        component: str = "VTextField",
        field_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        props: Dict[str, Any] = {"model": model, "label": label}
        if field_type:
            props["type"] = field_type
        return {
            "component": "VCol",
            "props": {"cols": 12, "sm": 6, "md": 4},
            "content": [{"component": component, "props": props}],
        }

    def get_page(self) -> List[dict]:
        history = self.get_data("sign_history") or []
        if not isinstance(history, list) or not history:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": "暂无签到记录",
                    },
                }
            ]

        items = []
        for item in reversed(history[-100:]):
            if not isinstance(item, dict):
                continue
            rank = "-"
            if item.get("rank") is not None:
                rank = str(item["rank"])
                if item.get("total") is not None:
                    rank += f" / {item['total']}"
            items.append(
                {
                    "date": item.get("date", "-"),
                    "status": item.get("status", "未知"),
                    "gain": item.get("gain") if item.get("gain") is not None else "-",
                    "rank": rank,
                    "message": item.get("message", "-"),
                }
            )

        return [
            {
                "component": "VDataTable",
                "props": {
                    "headers": [
                        {"title": "时间", "key": "date", "sortable": True},
                        {"title": "状态", "key": "status", "sortable": True},
                        {"title": "奖励", "key": "gain", "sortable": True},
                        {"title": "排名/总数", "key": "rank", "sortable": False},
                        {"title": "结果", "key": "message", "sortable": False},
                    ],
                    "items": items,
                    "items-per-page": 20,
                    "density": "compact",
                    "hover": True,
                },
            }
        ]

    def stop_service(self):
        if self._scheduler:
            try:
                self._scheduler.cancel()
            except Exception as error:
                logger.warning("停止 NodeSeek 临时调度器失败：%s", error)
            finally:
                self._scheduler = None
