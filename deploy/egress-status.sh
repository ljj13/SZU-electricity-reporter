#!/bin/bash
# 专用本机出口代理状态检查（含真实连通性探测）
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${SZU_EGRESS_PORT:-7899}"

echo "== 进程 =="
pgrep -af "^$DIR/mihomo" || echo "  (未运行)"

echo "== 监听 =="
ss -lnt 2>/dev/null | grep "127.0.0.1:$PORT" || echo "  (未监听 127.0.0.1:$PORT)"

echo "== 选中的节点 =="
python3 - <<PY
import json, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:9998/proxies/REMOTE", timeout=5) as r:
        data = json.load(r)
    print("  now =", data.get("now"), "| 候选 =", len(data.get("all", [])))
except Exception as exc:
    print("  API 不可用:", exc)
PY

echo "== 出口连通性 =="
curl -sS -o /dev/null -w "  Server酱  https://sctapi.ftqq.com  -> %{http_code} %{errormsg}\n" \
  --max-time 15 -x "http://127.0.0.1:$PORT" "https://sctapi.ftqq.com/" 2>&1 | tail -1
curl -sS -o /dev/null -w "  OpenMeteo https://api.open-meteo.com -> %{http_code} %{errormsg}\n" \
  --max-time 15 -x "http://127.0.0.1:$PORT" \
  "https://api.open-meteo.com/v1/forecast?latitude=22.5&longitude=113.9&forecast_days=1&daily=temperature_2m_max" 2>&1 | tail -1
curl -sS -o /dev/null -w "  校园内网  192.168.84.3:9090          -> %{http_code} %{errormsg}\n" \
  --max-time 8 "http://192.168.84.3:9090/cgcSims/" 2>&1 | tail -1

echo "== 内存 =="
pid="$(pgrep -f "^$DIR/mihomo" | head -1)"
[ -n "$pid" ] && ps -o pid,rss,etime -p "$pid" | tail -1 || true
