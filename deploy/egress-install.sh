#!/bin/bash
# 专用本机出口代理 —— 安装/刷新（仅监听 127.0.0.1:7899）
#
# 背景：校园网直连 Server酱(sctapi.ftqq.com) 被拒；ShellCrash 的规则把国内域名
#       (RULE-SET,cn / cnip) 判给「本地直连」，因此经 7890 也走不通。
#       本实例用同一内核 + 同一订阅，但规则只有 MATCH->REMOTE，并把节点限定为
#       实测可达 Server酱 的 IPv6 节点。
#
# 安全性：
#   - 只监听 127.0.0.1:7899，不修改 ShellCrash 配置、不重启 ShellCrash、不设置全局代理
#   - 订阅地址只在安装时从 ShellCrash 运行配置读取，写入本目录 0600 的 config.yaml，
#     不进入任何仓库
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
CORE_SRC="${CORE_SRC:-/tmp/ShellCrash/CrashCore}"
SC_CONFIG="${SC_CONFIG:-/tmp/ShellCrash/config.yaml}"
PORT="${SZU_EGRESS_PORT:-7899}"
FORCE="${1:-}"

mkdir -p "$DIR/providers"

if [ ! -x "$DIR/mihomo" ] || [ "$FORCE" = "--force-core" ]; then
  if [ ! -x "$CORE_SRC" ]; then
    echo "错误：找不到可执行内核 $CORE_SRC" >&2
    exit 1
  fi
  cp -f "$CORE_SRC" "$DIR/mihomo" || exit 1
  chmod 700 "$DIR/mihomo"
  echo "内核已复制：$CORE_SRC -> $DIR/mihomo"
fi

if [ ! -f "$DIR/config.yaml" ] || [ "$FORCE" = "--force-config" ]; then
  SUB="$(python3 - "$SC_CONFIG" <<'PY'
import re
import sys

try:
    text = open(sys.argv[1], encoding='utf-8', errors='replace').read()
except OSError:
    sys.exit(0)

match = re.search(r'url:\s*"(https://[^"]*subscribe[^"]*)"', text)
if not match:
    match = re.search(r'url:\s*"(https://[^"]+)"', text)
print(match.group(1) if match else '')
PY
)"
  if [ -z "$SUB" ]; then
    echo "错误：无法从 $SC_CONFIG 读取订阅地址（可用 SC_CONFIG=... 指定）" >&2
    exit 1
  fi

  cat > "$DIR/config.yaml" <<EOF
# szu-egress：szu-electricity-reporter 专用本机出口（仅 127.0.0.1:$PORT）
# 规则只有 MATCH->REMOTE，不做 CN 分流；节点限定为实测可达 Server酱 的 IPv6 节点。
mixed-port: $PORT
allow-lan: false
mode: rule
log-level: warning
ipv6: true
unified-delay: true
tcp-concurrent: true
external-controller: 127.0.0.1:9998
dns:
  enable: false
proxy-providers:
  szu:
    type: http
    url: "$SUB"
    path: ./providers/szu.yaml
    interval: 86400
    health-check:
      enable: true
      url: "https://www.gstatic.com/generate_204"
      interval: 600
      timeout: 3000
proxy-groups:
  - name: REMOTE
    type: url-test
    use: [szu]
    filter: "IPv6"
    url: "https://www.gstatic.com/generate_204"
    interval: 300
    tolerance: 150
    lazy: true
rules:
  - MATCH,REMOTE
EOF
  chmod 600 "$DIR/config.yaml"
  echo "配置已生成：$DIR/config.yaml（0600，含订阅地址）"
fi

"$DIR/mihomo" -d "$DIR" -f "$DIR/config.yaml" -t >/dev/null 2>&1 || {
  echo "错误：config.yaml 语法检查失败" >&2
  "$DIR/mihomo" -d "$DIR" -f "$DIR/config.yaml" -t >&2 || true
  exit 1
}
echo "配置语法检查通过"
