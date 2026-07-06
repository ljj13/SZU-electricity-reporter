import crawler
import sc_sender
import data_store
import analysis
import weather
import config_gui

import json
import logging
from logging.handlers import TimedRotatingFileHandler
import argparse
import signal
import sys
from pathlib import Path
import datetime

import schedule
import time

# ── 日志配置 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
# exe 模式下用 exe 所在目录，否则用脚本所在目录
APP_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else SCRIPT_DIR
LOG_FILE = APP_DIR / 'electricity.log'
RUN_STATE_FILE = APP_DIR / 'last_success_date.txt'

logger = logging.getLogger('electricity')
logger.setLevel(logging.DEBUG)

# 控制台 handler
if sys.stdout:
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setLevel(logging.INFO)
    _ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    logger.addHandler(_ch)

# 文件 handler（按天轮转，保留 7 天）
_fh = TimedRotatingFileHandler(LOG_FILE, when='midnight', backupCount=7, encoding='utf-8')
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
_fh.suffix = '%Y-%m-%d'
logger.addHandler(_fh)

# ── 全局标志 ─────────────────────────────────────────────
_running = True


def _shutdown_handler(signum, frame):
    global _running
    logger.info('收到终止信号 (%s)，正在退出...', signum)
    _running = False


signal.signal(signal.SIGINT, _shutdown_handler)
signal.signal(signal.SIGTERM, _shutdown_handler)


# ── 配置读取 ─────────────────────────────────────────────
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
}


CONFIG_TEMPLATE = '''{
  "room_name": "",                // 宿舍房间号
  "room_id": "",                  // 楼栋ID，抓包获取
  "client": "",                   // 内网IP，抓包获取
  "interval_day": 14,             // 拉取最近天数
  "remind_daily": false,          // 是否每日提醒
  "server_chan_key": "",           // Server酱SendKey
  "remind_time": 9,               // 每日提醒时间（0-23时）
  "city": "",                     // 城市，用于获取气温，可精确到区
  "dry_run": false,               // true 时只抓取和保存，不发送微信
  "low_power_threshold": 20        // 低电量提醒阈值
}
'''


def _get_config_path():
    """获取 config.json 路径（exe 所在目录或脚本所在目录）。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / 'config.json'
    return SCRIPT_DIR / 'config.json'


def getConfig():
    config_path = _get_config_path()
    if not config_path.exists():
        if getattr(sys, 'frozen', False):
            return DEFAULT_CONFIG.copy()
        config_path.write_text(CONFIG_TEMPLATE, encoding='utf-8')
        logger.info('已生成配置模板: %s', config_path)
        logger.error('请填写 config.json 后重新运行')
        sys.exit(1)
    with open(config_path, encoding='utf-8') as f:
        lines = f.readlines()
    cleaned = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith('//'):
            continue
        idx = line.find('  //')
        if idx != -1:
            line = line[:idx] + '\n'
        cleaned.append(line)
    config = DEFAULT_CONFIG.copy()
    config.update(json.loads(''.join(cleaned)))
    return config


def validate_config(config: dict) -> list:
    """校验配置参数，返回错误列表（空列表表示全部通过）。"""
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

    sc_key = config.get('server_chan_key', '')
    if sc_key and not sc_key.startswith('SCT') and not sc_key.startswith('http'):
        errors.append(f'server_chan_key 格式异常，应以 SCT 开头或 http 开头，当前值: {sc_key}')

    return errors


def run_once_per_day(task, today: str = None, state_path: Path = RUN_STATE_FILE,
                     force: bool = False) -> bool:
    """同一天最多执行一次成功任务；失败不占用当天名额。"""
    today = today or str(datetime.date.today())
    state_path = Path(state_path)

    if not force and state_path.exists():
        last_success = state_path.read_text(encoding='utf-8').strip()
        if last_success == today:
            logger.info('今日任务已成功执行过，跳过本次触发')
            return False

    ok = bool(task())
    if ok:
        state_path.write_text(today, encoding='utf-8')
    return ok


# ── 核心任务 ─────────────────────────────────────────────
def job(config: dict = None):
    """执行一次电量查询 + 推送，带异常保护，不会因单次失败退出整个程序。"""
    try:
        config = config or getConfig()
        room_name = config['room_name']
        room_id = config['room_id']
        client = config['client']

        # room_id → 楼栋名
        ROOM_ID_MAP = {
            '58': '桃李斋', '61': '银桦斋', '56': '米兰斋', '54': '山茶斋',
            '59': '凌霄斋', '57': '海桐斋', '55': '红榴斋', '18118': '聚翰斋',
            '18120': '红豆斋', '18119': '紫薇斋', '7126': '风槐斋', '7603': '雨鹃斋',
            '17887': '蓬莱客舍',
            '73': '杜衡阁', '70': '文杏阁', '71': '海棠阁', '74': '辛夷阁',
            '77': '紫藤轩', '65': '紫檀轩', '66': '石楠轩', '68': '芸香阁',
            '76': '云杉轩', '75': '韵竹阁', '72': '疏影阁', '63': '木犀轩',
            '64': '丹枫轩', '67': '苏铁轩', '69': '丁香阁',
            '7724': '乔梧阁', '7725': '乔梧阁', '6876': '乔森阁', '6875': '乔森阁',
            '6122': '乔木阁', '6364': '乔木阁', '6877': '乔相阁', '6878': '乔相阁',
            '6121': '乔林阁', '6363': '乔林阁', '8147': '留学生公寓',
            '10057': '风信子', '10934': '山楂树', '10935': '胡杨林',
            '7119': '春笛', '8240': '冬筑', '8241': '冬筑', '8242': '冬筑',
            '8092': '冬筑',
        }
        building = ROOM_ID_MAP.get(room_id, '')
        interval_day = config['interval_day']
        sc_key = config.get('server_chan_key', '')
        dry_run = config.get('dry_run', False)

        if room_name == '' or room_id == '':
            logger.error('未配置 config.json 中的 room_name / room_id')
            return False

        # 获得数据
        logger.info('开始爬取 %s 电量数据...', room_name)
        table_data = crawler.crawlData(client, room_name, room_id, interval_day)
        if len(table_data) == 0:
            logger.error('爬取数据失败，请检查是否能访问电费查询网站 http://192.168.84.3:9090/cgcSims/')
            return False
        logger.info('爬取数据结束，共 %d 条记录', len(table_data))

        # 处理数据
        data = processingData(table_data)
        logger.info('数据处理结束')

        # 在控制台格式化输出
        printData(data)

        # 保存到 CSV
        data_store.save(data)

        # 获取气温数据并更新 CSV（深圳大学南山区）
        import datetime
        today = datetime.date.today()
        start = today - datetime.timedelta(days=interval_day)
        temp_map = weather.fetch_temperature(str(start), str(today))
        for row in data:
            mm_dd = row['date']
            if mm_dd in temp_map:
                data_store.update_temp(mm_dd, temp_map[mm_dd])
                row['temp'] = temp_map[mm_dd]
        logger.info('气温数据更新完成')

        # 用电规律分析
        analysis_text = analysis.analyze()
        logger.info('分析完成')

        location = f'{building}{room_name}' if building else room_name
        describe = f'{location}电量查询'

        if dry_run:
            logger.info('dry_run=true，已跳过微信推送')
        elif sc_key:
            send_msg = sc_sender.handle(
                data, describe, analysis_text,
                low_power_threshold=config.get('low_power_threshold'))
            if not sc_sender.send(key_url=sc_key, data=send_msg):
                return False
            logger.info('已发送至微信')
        else:
            logger.info('未配置 server_chan_key，跳过微信推送')
        return True

    except Exception:
        logger.exception('任务执行异常')
        return False


# ── 数据处理（原逻辑不变） ───────────────────────────────
def processingData(table_data: list):
    data = []
    day_num = len(table_data)

    for i in range(day_num - 1):
        charge = table_data[i + 1][3] - table_data[i][3]
        data.append({
            'date': table_data[i][0],
            'cost': table_data[i][1] - table_data[i + 1][1],
            'rest': table_data[i][1],
            'charge': charge
        })
        if charge != 0:
            data[-1]['cost'] += charge
        else:
            data[-1]['charge'] = '-'

    data.append({
        'date': table_data[day_num - 1][0],
        'cost': '-',
        'rest': table_data[day_num - 1][1],
        'charge': '-'
    })

    # 最新日期在前
    data.reverse()

    # 日期去掉年份，只保留 MM-DD
    for row in data:
        row['date'] = row['date'][5:]

    return data


# ── 控制台输出（原逻辑不变） ─────────────────────────────
def printData(data: list):
    header = f"{'日期':<8}{'用电':<8}{'剩余':<8}{'充电':<8}"
    logger.info(header)
    for row in data:
        parts = []
        for datum in row:
            value = row[datum]
            if isinstance(value, float):
                parts.append(f'{value:<12.2f}')
            else:
                parts.append(f'{str(value):<12}')
        logger.info(''.join(parts))


# ── 主入口 ───────────────────────────────────────────────
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='SZU 宿舍电量微信提醒')
    parser.add_argument('--force', action='store_true',
                        help='忽略今天已成功执行记录，强制运行一次')
    parser.add_argument('--dry-run', action='store_true',
                        help='本次只抓取和保存，不发送微信')
    parser.add_argument('--configure', action='store_true',
                        help='打开配置窗口并保存 config.json')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config_path = _get_config_path()
    if args.configure and not config_path.exists():
        config = DEFAULT_CONFIG.copy()
    else:
        config = getConfig()
    if args.dry_run:
        config['dry_run'] = True

    # 配置校验
    errors = validate_config(config)
    if args.configure or (getattr(sys, 'frozen', False) and errors):
        next_config = config_gui.configure(
            config, DEFAULT_CONFIG, validate_config, _get_config_path(), errors)
        if next_config is None:
            logger.error('配置未保存，程序退出')
            return
        config = next_config
        errors = validate_config(config)

    if errors:
        for err in errors:
            logger.error('配置错误: %s', err)
        logger.error('请检查 config.json 后重新运行')
        return

    remind_daily = config.get('remind_daily', False)
    remind_time = config.get('remind_time', 9)

    # 立即尝试执行一次；若今天已成功执行过，则不会重复消耗推送额度。
    run_once_per_day(lambda: job(config), force=args.force)

    if not remind_daily:
        logger.info('未开启每日提醒，程序退出')
        return

    # 使用 schedule 安排每日定时任务
    schedule.every().day.at(f'{remind_time:02d}:00').do(
        run_once_per_day, lambda: job(config))
    logger.info('已开启每日提醒，每天 %02d:00 执行', remind_time)

    while _running:
        next_run = schedule.idle_seconds()
        if next_run is None:
            break
        if next_run > 0:
            time.sleep(next_run)
        schedule.run_pending()

    logger.info('程序已退出')


if __name__ == '__main__':
    main()
