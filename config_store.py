import json
import sys
from pathlib import Path


DEFAULT_CONFIG = {
    "room_name": "",
    "room_id": "",
    "client": "",
    "interval_day": 14,
    "remind_daily": False,
    "server_chan_key": "",
    "remind_time": 9,
    "city": "",
    "dry_run": False,
    "low_power_threshold": 20,
    # ── 网络出口（本机代理，不影响系统/全局代理）──
    "proxy_url": "http://127.0.0.1:7899",           # 专用本机出口（仅本项目使用）
    "proxy_fallback_url": "http://127.0.0.1:7890",  # 备用：ShellCrash 现有代理
    "server_chan_egress": "proxy,fallback,direct",  # Server酱出口链
    "weather_egress": "proxy,fallback,direct",      # 天气出口链
    "push_retries": 2,                              # 每个出口的尝试次数
    "push_timeout": 20,                             # 单次请求读超时（秒）
}


CONFIG_TEMPLATE = '''{
  "room_name": "",                // 宿舍房间号
  "room_id": "",                  // 楼栋ID，抓包获取
  "client": "",                   // 内网IP，抓包获取
  "interval_day": 14,             // 拉取最近天数
  "remind_daily": false,          // 是否每日提醒
  "server_chan_key": "",          // Server酱SendKey
  "remind_time": 9,               // 每日提醒时间（0-23时）
  "city": "",                    // 城市，用于获取气温，可精确到区
  "dry_run": false,               // true 时只抓取和保存，不发送微信
  "low_power_threshold": 20,      // 低电量提醒阈值

  // ── 网络出口（只对本程序生效，不设置系统/全局代理）──
  // 校园内网电量接口始终直连，不受以下配置影响。
  "proxy_url": "http://127.0.0.1:7899",           // 专用本机出口
  "proxy_fallback_url": "http://127.0.0.1:7890",  // 备用本机出口（ShellCrash）
  "server_chan_egress": "proxy,fallback,direct",  // Server酱出口顺序
  "weather_egress": "proxy,fallback,direct",      // 天气出口顺序（失败不影响推送）
  "push_retries": 2,                              // 每个出口的尝试次数
  "push_timeout": 20                              // 单次请求读超时（秒）
}
'''


def get_config_path() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / 'config.json'
    return Path(__file__).resolve().parent / 'config.json'


def strip_json_comments(text: str) -> str:
    """Remove // comments while preserving strings."""
    result = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ''
        if char == '"' and not escaped:
            in_string = not in_string
        if not in_string and char == '/' and next_char == '/':
            while index < len(text) and text[index] not in '\r\n':
                index += 1
            continue
        result.append(char)
        escaped = (char == '\\' and not escaped)
        if char != '\\':
            escaped = False
        index += 1
    return ''.join(result)


def read_config(config_path: Path = None) -> dict:
    config_path = config_path or get_config_path()
    if not config_path.exists():
        return DEFAULT_CONFIG.copy()
    config = DEFAULT_CONFIG.copy()
    config.update(json.loads(strip_json_comments(config_path.read_text(encoding='utf-8'))))
    return config


def save_config(config: dict, config_path: Path = None):
    config_path = config_path or get_config_path()
    merged = DEFAULT_CONFIG.copy()
    merged.update(config)
    config_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')


def validate_config(config: dict) -> list:
    errors = []

    if not config.get('room_name'):
        errors.append('room_name 不能为空，请填写宿舍房间号')
    if not config.get('room_id'):
        errors.append('room_id 不能为空，请填写楼栋 ID')
    if not config.get('client'):
        errors.append('client 不能为空，请填写内网 IP')

    interval = config.get('interval_day')
    if not isinstance(interval, int) or interval < 1:
        errors.append(f'interval_day 必须是正整数，当前值: {interval}')

    remind_time = config.get('remind_time')
    if not isinstance(remind_time, int) or not (0 <= remind_time <= 23):
        errors.append(f'remind_time 必须是 0-23 的整数，当前值: {remind_time}')

    threshold = config.get('low_power_threshold')
    if not isinstance(threshold, (int, float)) or threshold <= 0:
        errors.append(f'low_power_threshold 必须是正数，当前值: {threshold}')

    sc_key = config.get('server_chan_key', '')
    if sc_key and not sc_key.startswith('SCT') and not sc_key.startswith('http'):
        errors.append('server_chan_key 格式异常，应以 SCT 开头或 http 开头')

    # ── 网络出口配置（错误只提示，不阻断已有配置的运行）──
    valid_tokens = {'direct', 'proxy', 'fallback'}
    for key, label in (('server_chan_egress', 'Server酱出口'),
                       ('weather_egress', '天气出口')):
        value = config.get(key, '')
        tokens = [t.strip().lower() for t in str(value).split(',') if t.strip()]
        if not tokens:
            errors.append(f'{key} 不能为空（可选 proxy/fallback/direct）')
        elif any(t not in valid_tokens for t in tokens):
            errors.append(f'{label} {key} 含未知出口: {value}'
                          f'（可选 {"、".join(sorted(valid_tokens))}）')

    for key in ('proxy_url', 'proxy_fallback_url'):
        value = str(config.get(key, '') or '')
        if value and not (value.startswith('http://') or value.startswith('https://')):
            errors.append(f'{key} 必须是 http:// 或 https:// 开头的本机代理地址，当前值: {value}')

    retries = config.get('push_retries')
    if not isinstance(retries, int) or not (1 <= retries <= 5):
        errors.append(f'push_retries 必须是 1-5 的整数，当前值: {retries}')

    timeout = config.get('push_timeout')
    if not isinstance(timeout, (int, float)) or not (1 <= timeout <= 120):
        errors.append(f'push_timeout 必须是 1-120 的秒数，当前值: {timeout}')

    return errors
