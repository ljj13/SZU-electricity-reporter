# 修复与验证记录 — 2026-10-09

## 1. 根因（证据链）

| # | 现象 | 证据 | 结论 |
|---|------|------|------|
| 1 | 2026-09-08 之后每日推送全部失败 | `last_success_date.txt` 停在 09-08；`electricity.log*` 每次 `ConnectionRefusedError [Errno 111]`；`last_error.txt` 最新 2026-10-08 09:00:17 | 旧代码 `requests.request()` 无出口配置，直连 `sctapi.ftqq.com:443` 被拒（75 ms 内 RST） |
| 2 | 天气长期失败 | `近期气温获取失败` 堆栈 | `weather.py` `trust_env = False` 且无代理，直连 `api.open-meteo.com` 被拒 |
| 3 | 经 ShellCrash `7890` 也失败 | `curl -x 127.0.0.1:7890 https://sctapi.ftqq.com` 8/8 TLS EOF | ShellCrash 规则 `RULE-SET,cn` / `RULE-SET,cnip` → `🎯 本地直连(DIRECT)`；CN 域名不走节点 |
| 4 | 代理节点可达 Server酱 | mihomo `/proxies/<组>/delay?url=https://sctapi.ftqq.com` → `🚀 节点选择` 215 ms、`三毛机场` 290 ms；`🎯 本地直连` 失败 | 节点本身可达，问题在规则分流 |
| 5 | 只有 IPv6 节点可达 CN 目标 | 47 个节点逐个延时测试：8 个 IPv6 节点成功（238–579 ms），39 个 IPv4 节点全部超时 | 出口需限定 `filter: "IPv6"` |

补充事实：校园网并非整体封锁公网 v4（`http://www.baidu.com` 直连 200）；板子原生 IPv6 可用
（`curl -6 https://www.cloudflare.com` → 200），但 `sctapi.ftqq.com` 无 AAAA 记录，无法直接走 v6。

## 2. 修复方案

新增 `net_egress.py`，把出网集中配置化（不设置任何全局代理，`trust_env=False`）：

```
校园内网 192.168.84.3:9090  -> direct（强制）
sctapi.ftqq.com            -> proxy(127.0.0.1:7899) -> fallback(127.0.0.1:7890) -> direct
api.open-meteo.com         -> 同上，失败仅告警
```

`127.0.0.1:7899` 是**本项目专用**的本机出口：复用 ShellCrash 的 mihomo 内核二进制与同一订阅，
但 `mode: rule` + 唯一规则 `MATCH,REMOTE` + `filter: "IPv6"`，只监听回环地址。
不改动、不重启 ShellCrash，不修改其 `/tmp/ShellCrash/config.yaml`（验证 mtime 未变）。

其它修改：超时/有界重试、异常隔离（天气/分析/CSV 失败不阻断推送）、退出码、
原子状态写入、`--test-push`（不写状态）、`--quiet`、cron 重试窗口与包装脚本。

## 3. 测试结果

- 离线单元测试 **68 项通过**（本地 Python 3.14 与板端 Python 3.13 各跑一次）
  `python -m unittest discover -s tests -t .`
- 本地/板端 26 个关键文件 SHA-256 逐一比对一致。

## 4. 板端实测（EAIDK-310，内核 6.18.55-eaidk310-wifi3，根 /dev/mmcblk2p2）

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 出口连通性 | `egress/status.sh` | Server酱 200、OpenMeteo 200、校园内网 200；选中 IPv6 香港节点，候选 8 |
| 全流程 dry-run | `main.py --dry-run --once` | exit 0；采集 13 条、CSV 更新、**气温恢复**（15 天，补全 14 条）、分析完成；未推送、状态文件未变 |
| 受控测试推送 | `main.py --test-push` | exit 0；`HTTP 200 / Server酱推送成功`；`last_success_date.txt` md5 未变（不占用当日名额） |
| 失败路径 | 临时副本 + 死代理（出口链仅 `proxy`） | exit 1；`last_error.txt` 记录“推送网络失败：所有出口均不可用”；**未写状态**；天气失败仅告警 |
| 有界重试 | `net_egress.request` 死代理 + direct | 2.2 s 内按预期失败，日志为单行摘要 |
| cron 最小环境 | `env -i HOME=... bash run-once.sh --dry-run` | exit 0，6 s；cron.log 正常轮转写入 |
| 出口自愈 | 先 `stop.sh`，再跑上面的 cron 命令 | 出口自动重启并监听 127.0.0.1:7899 |
| 权限 | `stat` | `config.json` 600、出口 `config.yaml` 600、`run-once.sh` 775 |
| 既有服务 | `systemctl is-active` | `cron` active、`shellcrash.service` active；ShellCrash 运行配置 mtime 未变 |
| 去重 | `main.py --once`（当日已成功） | `skipped`，无新增发送，退出码 0 |

## 5. 事件记录（透明披露）

- 03:32:37 受控测试推送成功（用户微信收到一条标注“【测试】”的消息）。
- **03:33:19 意外发送了一份真实日报**：失败路径测试的临时副本未成功改写配置
  （脚本用 `json.loads` 读取带 `//` 注释的生产配置而抛错），于是走了正常出口，
  发送内容为 `预计还有 4 天需要充值电费 / <宿舍位置>`（Server酱 HTTP 200）。
- 处置：把当日完成记录如实写入生产 `last_success_date.txt`（`date=2026-10-09`，
  附 `note` 说明），使 09:00 及开机补跑均判定为“今日已完成”而跳过，避免重复推送；
  已实测 `skipped`。校验脚本随后改为 `config_store.read_config`（注释感知）。

## 6. 未完成项

- **重启持久性验证**：`busctl ... CanReboot` 返回 `challenge`，非交互会话无免密 sudo，
  本轮无法执行 `reboot`。已逐项验证可持续性机制：crontab 已落盘（`crontab -l` 可复现）、
  `@reboot` 启动出口 + `run-once.sh` 自愈（实测通过）、内核/配置/虚拟环境均在 eMMC 根分区、
  `cron` 与 `shellcrash` 服务 enabled。建议由操作员执行一次 `sudo reboot` 后复核。
