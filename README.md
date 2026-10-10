# SZU 宿舍电量微信提醒

自动查询深圳大学宿舍电量，通过 Server酱 Turbo 推送至微信，包含电量趋势图表、气温关联和用电预测。
支持 Windows（双击 exe、配置窗口、任务计划）与 Linux / 单板计算机（可配置网络出口、多级代理回退、cron 调度与自愈）。

## 功能

- 每日自动查询宿舍用电数据
- 剩余电量 / 用电量折线图（QuickChart 云端渲染，Y 轴自适应）
- 用电量图表叠加气温双轴对比
- 稳健日耗中位数与异常值过滤，预测充值时间和合理范围
- Open-Meteo Forecast API 获取最近 14 天及当天气温，自动关联每天用电
- 用电规律分析（周末 vs 工作日、周均、月度趋势、气温相关性）
- 历史数据持久化（CSV 文件，自动去重与补全）
- Server酱 Turbo 微信推送
- 每天最多成功推送一次，开机触发与定时触发共享同一状态，失败不占名额
- **Windows 支持**：双击 exe、Tkinter 配置窗口、任务计划程序安装与卸载脚本
- **Linux 支持**：网络出口多级回退策略（直连/专用代理/备用代理）、专用回环代理（127.0.0.1:7899）、cron 09:00~12:45 每 15 分钟重试、自愈机制与全套单元测试

## 平台与运行方式

### 方式一：Windows 快速开始（exe 版）

1. 从 [Releases](https://github.com/ljj13/SZU-electricity-reporter/releases) 下载 `szu-electricity-reporter.exe`
2. 把 exe 放到一个固定文件夹
3. 双击运行，首次会弹出配置窗口
4. 填写房间号、楼栋 ID、client、Server酱 SendKey 等信息后保存
5. exe 会把配置记录到同目录的 `config.json`，之后双击即可按配置运行

### 方式二：Windows 源码运行与任务计划

#### 1. 安装依赖

```bash
pip install requests schedule numpy
```

#### 2. 配置 config.json

参考下方配置说明或直接运行生成模板：

```bash
python main.py --configure
```

#### 3. 自动运行（Windows 任务计划）

源码版推荐使用 Windows 任务计划，执行结束自动退出，不长驻后台：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_scheduled_task.ps1
```

修改执行时间（例如每日 10:00）：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_scheduled_task.ps1 -DailyHour 10
```

卸载任务计划：

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall_scheduled_task.ps1
```

#### 4. 打包 exe（可选）

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name szu-electricity-reporter --hidden-import tkinter main.py
```

---

### 方式三：Linux / 单板计算机（EAIDK-310 等）部署

在受限校园网环境下（例如校园内网接口可达，但公网出口到微信推送接口被阻断），程序支持将网络出口配置化：

```
校园内网 192.168.84.3:9090  ── 强制 direct（显式无代理，不受环境变量影响）
sctapi.ftqq.com（Server酱） ── proxy(127.0.0.1:7899) -> fallback(127.0.0.1:7890) -> direct
api.open-meteo.com（天气）  ── proxy(127.0.0.1:7899) -> fallback(127.0.0.1:7890) -> direct（失败软降级）
```

- 核心出网采用显式 `Session(trust_env=False)`，绝不读写系统全局代理，不影响主机其他服务。
- 专用回环代理（`127.0.0.1:7899`，位于 `deploy/egress-*.sh`）复用现有代理内核与订阅，仅路由 IPv6 节点直达目标。

#### 1. 板端安装

```bash
# 复制源码到板端目录后执行
bash deploy/board-install.sh /path/to/staging
```

或使用 Windows 管理机通过 PowerShell 一键远程部署：

```powershell
pwsh -File deploy/deploy.ps1 -Board <板端IP> -User Fog
```

#### 2. Linux cron 调度

安装脚本会自动配置 crontab：

```cron
# 09:00 起每 15 分钟重试至 12:45，成功一次后自动跳过；开机自动补跑与出口自愈
@reboot sleep 60 && /home/Fog/.local/lib/szu-egress/start.sh >/dev/null 2>&1
@reboot sleep 90 && /home/Fog/szu-electricity-reporter/run-once.sh
*/15 9-12 * * * /home/Fog/szu-electricity-reporter/run-once.sh
```

- `run-once.sh` 具备出口未监听自动拉起自愈、日志自动轮转（≤512KB）、600 秒硬超时兜底和退出码透传。

#### 3. 常用运维与验证命令

```bash
python main.py --dry-run --once      # 全流程抓取与分析演练（不发微信、不占名额）
python main.py --test-push           # 受控连通性测试（发送一条标注测试的消息，不占日报名额）
python main.py --once                # 触发一次日常推送（受每日去重约束）
python main.py --once --force        # 忽略今日记录强制推送一次
python -m unittest discover -s tests -t .  # 运行全套 68 项自动化测试

bash ~/.local/lib/szu-egress/status.sh  # 检查出口状态与内网/Server酱/天气三目标连通性
bash ~/.local/lib/szu-egress/stop.sh    # 停止专用出口（回滚用）
```

---

## 配置说明（`config.json`）

`config.json` 支持 `//` 注释，真实的 `config.json` 已被 `.gitignore` 忽略。仓库提供 `config.example.json` 作为参考。

**基础参数：**

| 参数 | 说明 | 获取方式 / 默认值 |
|------|------|------------------|
| room_name | 房间号 | 抓包获取（必填） |
| room_id | 楼栋 ID | 抓包获取（必填） |
| client | 内网 IP | 抓包获取（必填） |
| interval_day | 拉取最近天数 | 14 |
| remind_daily | 每日自动提醒 | false |
| server_chan_key | Server酱 SendKey | 空（`SCT...`） |
| remind_time | 每日提醒时间（0-23 时） | 9 |
| dry_run | 只抓取、保存和分析，不发送微信 | false |
| low_power_threshold | 低电量阈值 | 20 |

**抓包方法：** 校内网打开 http://192.168.84.3:9090/cgcSims/ ，F12 → Network，选好宿舍后点查询，查看 `selectList.do` 的 POST 参数中的 `roomId`、`roomName`、`client`。

**网络出口参数（可选，默认值即可适配 Linux 单板）：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| proxy_url | 本机专用出口代理地址 | `http://127.0.0.1:7899` |
| proxy_fallback_url | 备用代理地址 | `http://127.0.0.1:7890` |
| server_chan_egress | Server酱出口尝试顺序 | `proxy,fallback,direct` |
| weather_egress | 天气接口出口尝试顺序 | `proxy,fallback,direct` |
| push_retries | 每个出口尝试次数（1-5） | 2 |
| push_timeout | 单次请求超时时间（秒） | 20 |

---

## 命令行参数一览

| 参数 | 说明 |
|------|------|
| `--once` | 执行一次后立即退出，供 Windows 任务计划程序或 Linux cron 调用 |
| `--dry-run` | 本次只抓取数据、计算趋势并更新 CSV，不发送微信推送，不占用当日成功名额 |
| `--force` | 忽略今日已成功执行的记录，强制运行一次 |
| `--test-push` | 仅发送一条标注为测试的消息以验证推送通道连通性，不写入成功状态，不影响当日正式日报 |
| `--quiet` | 关闭 stdout 输出（用于 Linux cron 或静默后台调用，应用日志仍正常记入 `electricity.log`） |
| `--configure` | 打开 Tkinter 配置窗口并保存 `config.json`（支持 Windows 桌面） |

---

## 文件说明

| 文件 / 目录 | 说明 |
|------------|------|
| `main.py` | 主程序：调度、参数解析、退出码契约、异常隔离与每日去重 |
| `net_egress.py` | 网络出口策略：多级出口链抽象、Session 隔离、有界重试、单行错误摘要 |
| `crawler.py` | 电量爬虫：请求 SIMS 电控系统，强制直连出口，带有限重试 |
| `sc_sender.py` | 消息格式化与 Server酱 Turbo API 推送，带出口链支持与 SendKey 遮蔽 |
| `weather.py` | 气温采集：Open-Meteo 历史与当天气温，失败软降级，不阻断主流程 |
| `data_store.py` | 数据持久化：CSV 读写、自动去重与气温补全，支持 `SZU_REPORTER_DIR` 测试隔离 |
| `charts.py` | 图表与预测：QuickChart 折线图、稳健日耗中位数预测与波动范围计算 |
| `analysis.py` | 用电规律分析：工作日 vs 周末、周均、月度汇总、气温相关性系数 |
| `config_store.py` | 配置管理：读取、写入、模板生成、出口参数校验 |
| `config_gui.py` | Windows 配置 GUI 对话框（Tkinter） |
| `buildings.py` | 楼栋 ID 到楼栋名映射表 |
| `run-once.sh` | Linux 定时任务包装脚本：出口自愈、日志轮转、硬超时与退出码透传 |
| `deploy/` | 部署与运维工具：专用出口管理、cron 安装、板端与远程安装脚本 |
| `tests/` | 自动化测试套件：68 项涵盖网络出口、重试、爬虫、去重状态机、异常隔离与退出码 |
| `docs/` | 验证记录与运维归档（包含 2026-10-09 实测与排障记录） |
| `install_scheduled_task.ps1` | Windows 登录及每日任务计划安装脚本 |
| `uninstall_scheduled_task.ps1` | Windows 任务计划卸载脚本 |
| `start_silent.vbs` | Windows 无窗口静默执行启动脚本 |

---

## 注意事项

- 必须在深大校内网环境下运行（用于访问 SIMS 内网电费系统）。
- `client` 值（内网 IP）可能会发生变化，查询失败时重新抓包更新即可。
- Server酱 Turbo 免费版有每日推送配额限制。
- 每日去重状态保存在 `last_success_date.txt`，失败信息保存在 `last_error.txt`（成功后自动归档为 `last_error.resolved.txt`）。
- 缺少 `config.json` 时会自动生成模板，填写后重新运行即可。
