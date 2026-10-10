#!/bin/bash
# 在板上执行：从 staging 目录安装/升级 szu-electricity-reporter。
# 用法： board-install.sh <staging-dir>
# 特性：不覆盖 config.json；升级前备份现有代码与 crontab；安装后跑测试。
set -u

APP_DIR="${APP_DIR:-/home/Fog/szu-electricity-reporter}"
EGRESS_DIR="${EGRESS_DIR:-/home/Fog/.local/lib/szu-egress}"
STAGE="${1:-}"
if [ -z "$STAGE" ] || [ ! -d "$STAGE" ]; then
  echo "用法: board-install.sh <staging-dir>" >&2
  exit 2
fi

TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backups/pre-upgrade-$TS"
mkdir -p "$BACKUP_DIR" "$APP_DIR/deploy" "$APP_DIR/tests" "$APP_DIR/logs"

echo "== 1/6 备份现有代码与 crontab =="
for name in main.py sc_sender.py weather.py crawler.py data_store.py analysis.py charts.py \
            config_store.py config_gui.py buildings.py net_egress.py run-once.sh requirements.txt; do
  [ -e "$APP_DIR/$name" ] && cp -p "$APP_DIR/$name" "$BACKUP_DIR/" 2>/dev/null
done
crontab -l > "$BACKUP_DIR/crontab-before-$TS.txt" 2>/dev/null || true
echo "   备份目录: $BACKUP_DIR"

echo "== 2/6 安装应用代码（保留 config.json / 数据 / 虚拟环境）=="
for file in "$STAGE"/*.py "$STAGE"/requirements.txt "$STAGE"/run-once.sh; do
  [ -e "$file" ] || continue
  cp -f "$file" "$APP_DIR/"
done
cp -f "$STAGE"/tests/*.py "$APP_DIR/tests/" 2>/dev/null
cp -f "$STAGE"/deploy/*.sh "$APP_DIR/deploy/" 2>/dev/null
chmod +x "$APP_DIR/run-once.sh" "$APP_DIR"/deploy/*.sh 2>/dev/null

echo "== 3/6 安装专用出口代理脚本到 $EGRESS_DIR =="
mkdir -p "$EGRESS_DIR"
cp -f "$STAGE"/deploy/egress-install.sh "$EGRESS_DIR/install.sh"
cp -f "$STAGE"/deploy/egress-start.sh "$EGRESS_DIR/start.sh"
cp -f "$STAGE"/deploy/egress-stop.sh "$EGRESS_DIR/stop.sh"
cp -f "$STAGE"/deploy/egress-status.sh "$EGRESS_DIR/status.sh"
chmod +x "$EGRESS_DIR"/*.sh

echo "== 4/6 安装/刷新出口配置并启动 =="
"$EGRESS_DIR/install.sh" || { echo "错误：出口安装失败" >&2; exit 1; }
"$EGRESS_DIR/start.sh" || { echo "警告：出口启动失败，run-once.sh 仍会自愈重试" >&2; }

echo "== 5/6 安装 crontab =="
APP_DIR="$APP_DIR" EGRESS_DIR="$EGRESS_DIR" bash "$APP_DIR/deploy/install-cron.sh" || exit 1

echo "== 6/6 板端自测 =="
cd "$APP_DIR" || exit 1
.venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -5

echo "安装完成。备份目录: $BACKUP_DIR"
