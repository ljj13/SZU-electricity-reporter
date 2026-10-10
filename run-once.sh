#!/bin/bash
# szu-electricity-reporter cron 包装脚本
#   1) 保证专用本机出口代理在监听（自愈，覆盖开机顺序不确定的情况）
#   2) 输出重定向到文件，绝不依赖 cron 的 stdout 邮件管道（避免写阻塞）
#   3) 硬超时兜底，退出码透传给 cron
set -u

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
EGRESS_DIR="${SZU_EGRESS_DIR:-$HOME/.local/lib/szu-egress}"
LOG_DIR="$APP_DIR/logs"
LOG_FILE="$LOG_DIR/cron.log"
MAX_BYTES=524288
KEEP_BYTES=262144
HARD_TIMEOUT="${SZU_RUN_TIMEOUT:-600}"
PORT="${SZU_EGRESS_PORT:-7899}"

mkdir -p "$LOG_DIR"

rotate_log() {
  [ -f "$LOG_FILE" ] || return 0
  local size
  size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
  if [ "$size" -gt "$MAX_BYTES" ]; then
    tail -c "$KEEP_BYTES" "$LOG_FILE" > "$LOG_FILE.tmp" 2>/dev/null && mv -f "$LOG_FILE.tmp" "$LOG_FILE"
  fi
}

port_open() {
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
    exec 3<&- 3>&-
    return 0
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -lnt 2>/dev/null | grep -q "127\.0\.0\.1:$PORT\b"
    return $?
  fi
  return 1
}

rotate_log

if ! port_open; then
  echo "[$(date '+%F %T')] 专用出口 127.0.0.1:$PORT 未监听，尝试启动 $EGRESS_DIR/start.sh" >> "$LOG_FILE"
  if [ -x "$EGRESS_DIR/start.sh" ]; then
    "$EGRESS_DIR/start.sh" >> "$LOG_FILE" 2>&1 \
      || echo "[$(date '+%F %T')] 出口启动失败，继续按备用出口/直连链尝试" >> "$LOG_FILE"
  else
    echo "[$(date '+%F %T')] 缺少 $EGRESS_DIR/start.sh" >> "$LOG_FILE"
  fi
fi

cd "$APP_DIR" || { echo "[$(date '+%F %T')] 缺少应用目录 $APP_DIR" >> "$LOG_FILE"; exit 1; }

timeout --signal=TERM "$HARD_TIMEOUT" .venv/bin/python main.py --once --quiet "$@" >> "$LOG_FILE" 2>&1
rc=$?
case "$rc" in
  0)   echo "[$(date '+%F %T')] run-once ok" >> "$LOG_FILE" ;;
  124) echo "[$(date '+%F %T')] run-once 超时被终止" >> "$LOG_FILE" ;;
  *)   echo "[$(date '+%F %T')] run-once 失败 rc=$rc（详见 electricity.log / last_error.txt）" >> "$LOG_FILE" ;;
esac
exit "$rc"
