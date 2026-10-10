#!/bin/bash
# 停止专用本机出口代理（回滚用）
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$DIR/egress.pid"

if [ -f "$PIDFILE" ]; then
  pid="$(cat "$PIDFILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null
  fi
  rm -f "$PIDFILE"
fi

pkill -f "^$DIR/mihomo" 2>/dev/null

sleep 1
if pgrep -f "^$DIR/mihomo" >/dev/null 2>&1; then
  echo "警告：进程仍在运行" >&2
  exit 1
fi
echo "专用出口已停止"
