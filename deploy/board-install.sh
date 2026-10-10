#!/bin/bash
# 在板上执行：从 staging 目录安装/升级 szu-electricity-reporter。
# 用法： board-install.sh <staging-dir>
# 特性：不覆盖 config.json；升级前备份现有代码与 crontab；失败自动回滚；安装后严格跑测试与退出码检查。
set -euo pipefail

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

rollback() {
  echo ">>> 正在执行自动回滚..." >&2
  if [ -d "$BACKUP_DIR" ]; then
    for f in "$BACKUP_DIR"/*; do
      [ -f "$f" ] || continue
      fname="$(basename "$f")"
      if [ "$fname" = "crontab-before-$TS.txt" ]; then
        if [ -s "$f" ]; then
          crontab "$f" 2>/dev/null || true
        fi
      else
        cp -pf "$f" "$APP_DIR/$fname" 2>/dev/null || true
      fi
    done
    if [ -d "$BACKUP_DIR/tests" ]; then
      cp -pf "$BACKUP_DIR/tests"/*.py "$APP_DIR/tests/" 2>/dev/null || true
    fi
    if [ -d "$BACKUP_DIR/deploy" ]; then
      cp -pf "$BACKUP_DIR/deploy"/*.sh "$APP_DIR/deploy/" 2>/dev/null || true
    fi
    echo ">>> 代码已回滚至升级前状态 ($BACKUP_DIR)" >&2
  fi
}

echo "== 1/6 备份现有代码与 crontab =="
mkdir -p "$BACKUP_DIR/tests" "$BACKUP_DIR/deploy"
for name in main.py sc_sender.py weather.py crawler.py data_store.py analysis.py charts.py \
            config_store.py config_gui.py buildings.py net_egress.py run-once.sh requirements.txt; do
  [ -e "$APP_DIR/$name" ] && cp -p "$APP_DIR/$name" "$BACKUP_DIR/" 2>/dev/null || true
done
[ -d "$APP_DIR/tests" ] && cp -p "$APP_DIR/tests"/*.py "$BACKUP_DIR/tests/" 2>/dev/null || true
[ -d "$APP_DIR/deploy" ] && cp -p "$APP_DIR/deploy"/*.sh "$BACKUP_DIR/deploy/" 2>/dev/null || true
crontab -l > "$BACKUP_DIR/crontab-before-$TS.txt" 2>/dev/null || true
echo "   备份目录: $BACKUP_DIR"

echo "== 2/6 安装应用代码（保留 config.json / 数据 / 虚拟环境）=="
for file in "$STAGE"/*.py "$STAGE"/requirements.txt "$STAGE"/run-once.sh; do
  [ -e "$file" ] || continue
  cp -f "$file" "$APP_DIR/"
done
cp -f "$STAGE"/tests/*.py "$APP_DIR/tests/" 2>/dev/null || true
cp -f "$STAGE"/deploy/*.sh "$APP_DIR/deploy/" 2>/dev/null || true
chmod +x "$APP_DIR/run-once.sh" "$APP_DIR"/deploy/*.sh 2>/dev/null || true

# 确保既有配置权限安全
if [ -f "$APP_DIR/config.json" ]; then
  chmod 600 "$APP_DIR/config.json" 2>/dev/null || true
fi

echo "== 3/6 安装专用出口代理脚本到 $EGRESS_DIR =="
mkdir -p "$EGRESS_DIR"
cp -f "$STAGE"/deploy/egress-install.sh "$EGRESS_DIR/install.sh"
cp -f "$STAGE"/deploy/egress-start.sh "$EGRESS_DIR/start.sh"
cp -f "$STAGE"/deploy/egress-stop.sh "$EGRESS_DIR/stop.sh"
cp -f "$STAGE"/deploy/egress-status.sh "$EGRESS_DIR/status.sh"
chmod +x "$EGRESS_DIR"/*.sh

echo "== 4/6 安装/刷新出口配置并启动 =="
if ! "$EGRESS_DIR/install.sh"; then
  echo "错误：出口安装失败" >&2
  rollback
  exit 1
fi

if ! "$EGRESS_DIR/start.sh"; then
  echo "警告：出口启动失败，run-once.sh 仍会自愈重试" >&2
fi

echo "== 5/6 安装 crontab =="
if ! APP_DIR="$APP_DIR" EGRESS_DIR="$EGRESS_DIR" bash "$APP_DIR/deploy/install-cron.sh"; then
  echo "错误：crontab 安装失败" >&2
  rollback
  exit 1
fi

echo "== 6/6 板端自测 =="
cd "$APP_DIR" || { rollback; exit 1; }

PYTHON_BIN=""
if [ -x "$APP_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$APP_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "错误：未找到 Python 执行环境（.venv/bin/python 或 python3）" >&2
  rollback
  exit 1
fi

echo "使用 Python 环境: $PYTHON_BIN"
TEST_LOG="$APP_DIR/logs/test-$TS.log"
mkdir -p "$APP_DIR/logs"

set +e
"$PYTHON_BIN" -m unittest discover -s tests -t . > "$TEST_LOG" 2>&1
TEST_EXIT=$?
set -e

if [ $TEST_EXIT -ne 0 ]; then
  echo "错误：板端自测试失败 (退出码 $TEST_EXIT)！" >&2
  echo "测试日志最后 25 行输出如下：" >&2
  tail -n 25 "$TEST_LOG" >&2
  rollback
  exit 1
fi

echo "板端自测全部通过 (退出码 0)。"
tail -n 5 "$TEST_LOG"

echo "安装完成。备份目录: $BACKUP_DIR"
