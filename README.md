# MoviePilot-Plugins

MoviePilot V2 第三方插件仓库，目前提供 NodeSeek 论坛自动签到插件。

## 插件列表

### NodeSeek论坛签到 (`nodeseeksign`)

- 使用 MoviePilot 内置 CloakBrowser 发起真实浏览器请求
- 支持随机奖励和固定 5 个鸡腿
- 按北京时间每天幂等执行
- 支持系统代理、失败重试、通知和签到历史
- 保留旧版插件 ID、配置前缀及历史数据键

## 安装

在 MoviePilot 插件市场的第三方仓库设置中添加：

```text
https://github.com/javazwz123/MoviePilot-Plugins
```

安装 `NodeSeek论坛签到` 后，在插件设置中填写 NodeSeek Cookie、签到周期并启用插件。

## 运行要求

- MoviePilot `>=2.12.0,<3`
- MoviePilot 内置 CloakBrowser 可正常启动
- MoviePilot 所在设备能够访问 `https://www.nodeseek.com`

本插件没有额外 Python 依赖，不会覆盖 MoviePilot 的共享依赖版本。

## 安全说明

Cookie 是登录凭证。请只保存到自己的 MoviePilot 配置中，不要提交到 Git、Issue、日志或截图。插件不会记录 Cookie，也不会把 Cookie 作为全局请求头；Cookie 仅按 `www.nodeseek.com` 域注入临时浏览器上下文。

仓库中的测试完全离线运行，使用模拟数据，不会访问 NodeSeek 或执行真实签到。

## 从旧版迁移

插件继续使用 `nodeseeksign` ID、`nodeseeksign_` 配置前缀、`sign_history` 和 `last_sign_date` 数据键。为避免同 ID 冲突，请在 MoviePilot 中只保留一个包含该插件的第三方仓库来源。

## 开发验证

```bash
python3 -m compileall -q plugins
python3 -m unittest discover -s tests -v
python3 scripts/check_plugin_versions.py package.json
```

## 许可证

本项目使用 [GPL-3.0](LICENSE)。第三方资源说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
