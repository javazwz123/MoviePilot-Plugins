# NodeSeek论坛签到

适用于 MoviePilot V2 的 NodeSeek 自动签到插件，源码位于 `plugins/nodeseeksign/`，插件 ID 为 `nodeseeksign`。插件通过 MoviePilot 内置 CloakBrowser 打开签到页，并在同源页面上下文中调用官方签到接口。

## 配置

| 配置项 | 说明 | 默认值 |
|---|---|---|
| 启用插件 | 注册定时签到服务 | 关闭 |
| 签到通知 | 发送签到结果通知 | 开启 |
| 随机奖励 | 开启为“试试手气”，关闭为固定 5 个鸡腿 | 开启 |
| 使用系统代理 | 使用 MoviePilot 的系统代理 | 关闭 |
| 立即运行一次 | 保存配置后执行一次，不受当日去重限制 | 关闭 |
| Cookie | NodeSeek 登录 Cookie | 空 |
| User-Agent | 可选；存在 `cf_clearance` 时建议与 Cookie 来源浏览器一致 | 空 |
| 签到周期 | Cron 表达式 | `0 8 * * *` |
| 浏览器超时 | 单次浏览器任务超时秒数 | `60` |
| 失败重试次数 | 首次失败后的附加尝试次数 | `1` |
| 重试间隔 | 两次尝试之间的等待秒数 | `30` |
| 历史保留天数 | 本地签到历史保留时间 | `30` |

## 执行流程

1. 在临时浏览器上下文中按 NodeSeek 域注入 Cookie。
2. 打开 `/board` 并确认页面识别到登录用户。
3. 查询 `/api/attendance/board?page=1`，已有当日记录则直接结束。
4. 未签到时执行 `POST /api/attendance?random=true|false`。
5. 再次查询签到榜，以服务端记录确认奖励和排名。
6. 成功后保存当日状态、历史并按配置发送通知。

## 常见问题

- `Cookie 已失效`：重新登录 NodeSeek 后更新 Cookie。
- 页面被拦截或返回 403：确认 MoviePilot 已升级至支持 CloakBrowser 的版本；必要时配置可用代理及对应 User-Agent。
- `CloakBrowser 运行环境不可用`：检查 MoviePilot 版本和健康检查，不要在插件目录单独安装或降级浏览器依赖。
- 重复来源冲突：从第三方仓库列表移除旧的同 ID 插件来源，只保留本仓库。

## 数据安全

不要在 Issue 中粘贴 Cookie、HAR、完整请求头或未经脱敏的 MoviePilot 日志。排查问题时只提供错误类型、HTTP 状态码和插件版本。
