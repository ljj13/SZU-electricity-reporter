#!/bin/bash
# 启动专用本机出口代理（幂等；已运行则直接返回 0）
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$DIR/mihomo"
CONF="$DIR/config.yaml"
PIDFILE="$DIR/egress.pid"
LOG="$DIR/egress.log"
PORT="${SZU_EGRESS_PORT:-7899}"

[ -x "$BIN" ] || { echo "错误：$BIN 不存在或不可执行（先运行 install.sh）" >&2; exit 1; }
[ -f "$CONF" ] || { echo "错误：$CONF 不存在（先运行 install.sh）" >&2; exit 1; }

if pgrep -f "^$BIN" >/dev/null 2>&1; then
  echo "出口已在运行"
  exit 0
fi

nohup "$BIN" -d "$DIR" -f "$CONF" >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"

for _ in $(seq 1 30); do
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
    exec 3<&- 3>&-
    echo "出口已监听 127.0.0.1:$PORT (pid $(cat "$PIDFILE"))"
    exit 0
  fi
  sleep 1
done

echo "错误：127.0.0.1:$PORT 未在 30 秒内监听，详见 $LOG" >&2
exit 1
