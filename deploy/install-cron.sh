#!/bin/bash
# 安装 Fog 用户 crontab：09:00 起每 15 分钟重试至 12:45，另有开机补跑。
# 只删除本项目相关行，其余 crontab 条目原样保留；旧表先备份。
set -u

APP_DIR="${APP_DIR:-/home/Fog/szu-electricity-reporter}"
EGRESS_DIR="${EGRESS_DIR:-/home/Fog/.local/lib/szu-egress}"
BACKUP_DIR="$APP_DIR/backups"
TS="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
KEEP=""
if crontab -l > "$BACKUP_DIR/crontab-before-$TS.txt" 2>/dev/null; then
  KEEP="$(crontab -l 2>/dev/null | grep -v -e 'szu-electricity-reporter' -e 'szu-egress' || true)"
else
  : > "$BACKUP_DIR/crontab-before-$TS.txt"
fi

{
  echo "# szu-electricity-reporter: 09:00 起每 15 分钟重试（程序自带每日去重，成功一次后自动跳过）"
  echo "@reboot sleep 60 && $EGRESS_DIR/start.sh >/dev/null 2>&1"
  echo "@reboot sleep 90 && $APP_DIR/run-once.sh"
  echo "*/15 9-12 * * * $APP_DIR/run-once.sh"
  if [ -n "$KEEP" ]; then
    printf '%s\n' "$KEEP"
  fi
} | crontab - || { echo "错误：crontab 安装失败" >&2; exit 1; }

echo "旧表备份：$BACKUP_DIR/crontab-before-$TS.txt"
echo "== 当前 crontab =="
crontab -l
