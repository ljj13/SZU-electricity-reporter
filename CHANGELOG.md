# 更新日志 (CHANGELOG)

所有重要的项目更新都将记录在此文件中。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，并遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

## [v1.1.0] - 2026-10-11

### 新增 (Added)
- **网络出口抽象与多级代理回退 (`net_egress.py`)**：集中管理全部外部出网请求。校园内网 SIMS 接口始终强制直连（无视环境代理）；Server酱与 Open-Meteo 天气接口支持 `proxy -> fallback -> direct` 出口链配置与有界重试。
- **Linux / 单板计算机专用出口与自愈体系 (`deploy/`, `run-once.sh`)**：
  - 专用回环代理（默认 `127.0.0.1:7899`），仅路由 IPv6 节点直达 Server酱，与宿主现有代理（如 ShellCrash 7890）和谐共存。
  - 定时调度包装脚本 `run-once.sh`：出口未监听自动拉起自愈、假死进程清理、日志自动轮转（≤512KB）以及 600 秒硬超时兜底。
  - crontab 调度策略：09:00 起每 15 分钟重试至 12:45，成功一次后自动跳过；支持开机补跑与出口自愈。
- **部署安全白名单 (`deploy/deploy.ps1`)**：建立严格的代码与部署文件白名单，配合硬编码敏感模式断言，杜绝 `config.json`（含 SendKey / 房间信息）与运行产物上传到暂存目录或 Git。
- **部署可靠性与失败自动回滚 (`deploy/board-install.sh`)**：修复管道退出码掩盖测试失败的隐患；开启 `set -euo pipefail`；升级前全量备份代码与 crontab，自测失败时自动执行 `rollback()` 回滚旧版。
- **跨平台终端编码自适应 (`_ensure_stdio_encoding()`)**：针对英文 Windows 及 CI 环境的 cp1252 终端代码页，自动平滑重配置为 UTF-8，彻底解决中文帮助信息 `UnicodeEncodeError` 崩溃。
- **自动化测试套件与 CI**：
  - 81 项跨平台单元与回归测试，覆盖网络出口、爬虫重试、每日去重状态机、异常隔离、配置兼容与部署安全。
  - GitHub Actions CI 工作流，全面覆盖 `ubuntu-latest` 和 `windows-latest` 环境下的 Python 3.10、3.11、3.12、3.13（共 8 个矩阵任务），包含 Shell 与 PowerShell 语法校验。
- **CLI 命令行**：新增 `--version` 参数。

### 修复与优化 (Fixed & Changed)
- **GUI 配置无损合并 (`config_gui.py`)**：修复在 Windows 配置窗口中保存配置时会覆盖高级出口参数的问题；抽离 `merge_gui_config` 纯函数，确保未在界面展示的自定义参数完整保留。
- **每日去重状态语义纠正 (`main.py`)**：修正未配置 `server_chan_key` 时误写 `last_success_date.txt` 的缺陷，增加 `update_state: False`，避免未真正推送抢占当日名额。
- **消除 POST 超时即时重试风险 (`net_egress.py`)**：Server酱等非幂等 POST 请求在遭遇 `ReadTimeout` 时，严格禁止即时重试或切换出口，防范重复发送通知风暴与配额耗尽。
- **异常隔离深化**：天气获取、用电规律分析和历史 CSV 写入异常仅告警记录，绝不阻断电费日报微信推送。

### 已知限制 (Known Limitations)
- **POST ReadTimeout 跨周期重试语义**：因 Server酱 Turbo API 不支持客户端幂等键（Idempotency-Key）或状态反查接口，若推送请求发生 `ReadTimeout`（请求已发但未收到服务商确认响应），系统单次内严禁即时重试；但为了防止宿舍欠费断电漏报，系统遵循 At-Least-Once 语义，在下一次 cron 周期（如 15 分钟后）仍会重试。若前一次超时实际已成功推送到微信，跨周期的重试可能产生重复通知。

---

## [v1.0.3] - 2026-07-16
- 新增 `--once` 一次性执行模式和跨进程单实例锁。
- 新增 Windows 任务计划安装与卸载脚本（登录时与每日固定时间触发）。
- 移除同日低电量额外推送，严格共用每日成功状态。
- 天气改用 Forecast API（近期历史与当天预报）。
- 预测改为最近一次充值后的真实日耗中位数并过滤异常值。

## [v1.0.2] - 2026-07-16
- 修复电量表格解析与浮点数处理健壮性。

## [v1.0.1] - 2026-07-06
- 增加 Tkinter 配置 GUI 对话框。
- 保护本地配置文件，移除调试代码。

## [v1.0.0] - 2026-05-05
- 初始发布：SIMS 宿舍电量抓取、Server酱微信推送、QuickChart 折线图、气温关联与用电预测。
