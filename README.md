# SZU 宿舍电量微信提醒

自动查询深圳大学宿舍电量，通过 Server酱 Turbo 推送至微信，包含电量趋势图表、气温关联和用电预测。

## 功能

- 每日自动查询宿舍用电数据
- 剩余电量 / 用电量折线图（QuickChart 云端渲染，Y 轴自适应）
- 用电量图表叠加气温双轴对比
- 最近一次充值后按真实日期估算日耗，使用中位数与异常值过滤预测充值时间和合理范围
- Open-Meteo Forecast API 获取最近 14 天及当天气温，自动关联每天用电
- 用电规律分析（周末 vs 工作日、周均、月度趋势、气温相关性）
- 历史数据持久化（CSV 文件，自动去重）
- Server酱 Turbo 微信推送
- 每天最多成功推送一次，开机触发与定时触发共享同一状态
- Windows 任务计划：登录时及每天固定时间执行一次，执行结束自动退出

## 快速开始（exe 版）

1. 从 [Releases](https://github.com/ljj13/SZU-electricity-reporter/releases) 下载 `szu-electricity-reporter.exe`
2. 把 exe 放到一个固定文件夹
3. 双击运行，首次会弹出配置窗口
4. 填写房间号、楼栋 ID、client、Server酱 SendKey 等信息后保存
5. exe 会把配置记录到同目录的 `config.json`，之后双击即可按配置运行

## 源码运行

### 1. 安装依赖

```bash
pip install requests schedule numpy
```

### 2. 配置 config.json

config.json 支持 `//` 行尾注释，首次运行会自动生成模板。真实的 `config.json` 已加入 `.gitignore`，请不要提交房间号、内网 IP、Server酱 SendKey 等私密信息；仓库中只保留 `config.example.json` 作为示例。

**必填参数：**

| 参数 | 说明 | 获取方式 |
|------|------|----------|
| room_name | 房间号 | 抓包获取 |
| room_id | 楼栋 ID | 抓包获取 |
| client | 内网 IP | 抓包获取 |

**选填参数：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| interval_day | 拉取最近天数 | 14 |
| remind_daily | 每日自动提醒 | false |
| server_chan_key | Server酱 SendKey | 空 |
| remind_time | 每日提醒时间（0-23 时） | 9 |
| dry_run | 只抓取、保存和分析，不发送微信 | false |
| low_power_threshold | 低电量阈值 | 20 |

**抓包方法：** 校内网打开 http://192.168.84.3:9090/cgcSims/ ，F12 → Network，选好宿舍后点查询，查看 `selectList.do` 的 POST 参数中的 `roomId`、`roomName`、`client`。

### 3. 运行

```bash
python main.py
```

- `remind_daily: false` → 查询一次后退出
- `remind_daily: true` → 常驻后台，每天定时查询并推送
- `dry_run: true` → 只抓取、保存和分析，不发送微信
- `python main.py --dry-run` → 本次临时不发送微信
- `python main.py --force` → 忽略今天已成功执行记录，强制运行一次
- `python main.py --configure` → 打开配置窗口并保存 `config.json`
- `python main.py --once` → 处理一次后立即退出，供 Windows 任务计划程序调用
- 成功执行后会写入 `last_success_date.txt`，同一天再次开机或到定时时间会自动跳过
- 最近一次失败会写入 `last_error.txt`，exe 无窗口运行时可用它排查问题

### 4. 打包 exe（可选）

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name szu-electricity-reporter --hidden-import tkinter main.py
```

打包后 exe 在 `dist/` 目录下，把 exe 和 config.json 放同一目录即可运行。

## 自动运行

源码版推荐使用 Windows 任务计划，而不是让 Python 进程整天常驻。安装脚本会创建一个任务，包含“登录时”和“每天 09:00”两个触发器，并自动移除旧启动文件夹快捷方式：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_scheduled_task.ps1
```

修改执行时间：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_scheduled_task.ps1 -DailyHour 10
```

卸载任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall_scheduled_task.ps1
```

任务计划与程序内的单实例锁、每日成功状态共同保证并发触发时也不会重复推送。

## 文件说明

| 文件 | 说明 |
|------|------|
| main.py | 主程序：定时调度、配置校验、日志系统 |
| config_gui.py | exe / 手动配置窗口 |
| config_store.py | 配置读取、保存、默认值、校验 |
| buildings.py | 楼栋 ID 到楼栋名映射 |
| crawler.py | 爬虫：请求 SIMS 电控系统，带重试和超时 |
| sc_sender.py | 推送：格式化消息，调用 Server酱 Turbo API |
| charts.py | 图表 + 预测：QuickChart 折线图、稳健日耗中位数预测与范围 |
| weather.py | 气温数据：Open-Meteo Forecast API 近期历史与当天气温 |
| data_store.py | 数据持久化：CSV 读写，自动去重 |
| analysis.py | 用电规律分析：周末/工作日、周均、月度趋势、气温相关性 |
| config.json | 配置文件（支持 // 注释） |
| requirements.txt | Python 依赖 |
| start_silent.vbs | 无窗口执行一次脚本（源码运行时使用） |
| install_scheduled_task.ps1 | 安装登录及每日任务计划 |
| uninstall_scheduled_task.ps1 | 删除任务计划 |

## 注意事项

- 必须在深大校内网环境下运行
- `client` 值（内网 IP）可能会变，查询失败时重新抓包更新
- Server酱 Turbo 免费版有每日推送次数限制，可考虑开通会员
- 电量数据更新有延迟，`remind_time` 不宜设置过早
- 历史数据保存在 `electricity_history.csv`，日期会按 `YYYY-MM-DD` 保存
- 缺少 config.json 时会自动生成模板，填写后重新运行即可
