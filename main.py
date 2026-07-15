import crawler
import sc_sender
import data_store
import analysis
import weather
import config_gui
import buildings
import config_store

import logging
from logging.handlers import TimedRotatingFileHandler
import argparse
import signal
import sys
from pathlib import Path
import datetime
import traceback

import schedule
import time

# ── 日志配置 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
# exe 模式下用 exe 所在目录，否则用脚本所在目录
APP_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else SCRIPT_DIR
LOG_FILE = APP_DIR / 'electricity.log'
RUN_STATE_FILE = APP_DIR / 'last_success_date.txt'
LAST_ERROR_FILE = APP_DIR / 'last_error.txt'

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


def _get_config_path():
    """获取 config.json 路径（exe 所在目录或脚本所在目录）。"""
    return config_store.get_config_path()


def getConfig():
    config_path = _get_config_path()
    if not config_path.exists():
        if getattr(sys, 'frozen', False):
            return config_store.DEFAULT_CONFIG.copy()
        config_path.write_text(config_store.CONFIG_TEMPLATE, encoding='utf-8')
        logger.info('已生成配置模板: %s', config_path)
        logger.error('请填写 config.json 后重新运行')
        sys.exit(1)
    return config_store.read_config(config_path)


def validate_config(config: dict) -> list:
    """校验配置参数，返回错误列表（空列表表示全部通过）。"""
    return config_store.validate_config(config)


def record_error(message: str, exc: BaseException = None):
    """Write the latest user-visible failure to last_error.txt."""
    lines = [
        f'time: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'error: {message}',
    ]
    if exc:
        lines.append('')
        lines.append('traceback:')
        lines.append(''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    LAST_ERROR_FILE.write_text('\n'.join(lines), encoding='utf-8')


def _read_run_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    text = state_path.read_text(encoding='utf-8').strip()
    if not text:
        return {}
    if text.startswith('{'):
        import json
        return json.loads(text)
    return {'date': text}


def _write_run_state(state_path: Path, today: str, info: dict = None):
    import json
    state = {
        'date': today,
        'sent_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    if info:
        state.update(info)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


def run_once_per_day(task, today: str = None, state_path: Path = RUN_STATE_FILE,
                     force: bool = False, repeat_task=None) -> bool:
    """同一天最多执行一次成功任务；失败不占用当天名额。"""
    today = today or str(datetime.date.today())
    state_path = Path(state_path)

    if not force and state_path.exists():
        state = _read_run_state(state_path)
        if state.get('date') == today:
            if repeat_task and not state.get('urgent_sent'):
                logger.info('今日已成功执行过，检查是否需要低电量额外提醒')
                result = repeat_task()
                if _task_success(result):
                    info = result if isinstance(result, dict) else {}
                    info['urgent_sent'] = True
                    _write_run_state(state_path, today, info)
                    return True
            logger.info('今日任务已成功执行过，跳过本次触发')
            return False

    result = task()
    ok = _task_success(result)
    if ok:
        info = result if isinstance(result, dict) else {}
        _write_run_state(state_path, today, info)
    return ok


def _task_success(result) -> bool:
    if isinstance(result, dict):
        return bool(result.get('ok'))
    return bool(result)


# ── 核心任务 ─────────────────────────────────────────────
def job(config: dict = None, urgent_only: bool = False):
    """执行一次电量查询 + 推送，带异常保护，不会因单次失败退出整个程序。"""
    try:
        config = config or getConfig()
        room_name = config['room_name']
        room_id = config['room_id']
        client = config['client']

        building = buildings.get_building_name(room_id)
        interval_day = config['interval_day']
        sc_key = config.get('server_chan_key', '')
        dry_run = config.get('dry_run', False)
        low_power_threshold = config.get('low_power_threshold')

        if room_name == '' or room_id == '':
            message = '未配置 config.json 中的 room_name / room_id'
            logger.error(message)
            record_error(message)
            return False

        # 获得数据
        logger.info('开始爬取电量数据...')
        table_data = crawler.crawlData(client, room_name, room_id, interval_day)
        if len(table_data) == 0:
            message = '爬取数据失败，请检查是否能访问电费查询网站 http://192.168.84.3:9090/cgcSims/'
            logger.error(message)
            record_error(message)
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
        latest = data[0] if data else {}
        latest_rest = latest.get('rest')

        if urgent_only:
            if not (isinstance(latest_rest, (int, float))
                    and low_power_threshold is not None
                    and latest_rest <= low_power_threshold):
                logger.info('当前电量未低于阈值，跳过低电量额外提醒')
                return False

        if dry_run:
            logger.info('dry_run=true，已跳过微信推送')
            return {
                'ok': True,
                'title': 'dry_run，未发送微信',
                'location': location,
            }
        elif sc_key:
            send_msg = sc_sender.handle(
                data, describe, analysis_text,
                low_power_threshold=low_power_threshold)
            if not sc_sender.send(key_url=sc_key, data=send_msg):
                record_error('Server酱推送失败，请查看 electricity.log')
                return False
            logger.info('已发送至微信')
            return {
                'ok': True,
                'title': send_msg.get('text', ''),
                'location': location,
                'urgent_sent': urgent_only,
            }
        else:
            logger.info('未配置 server_chan_key，跳过微信推送')
            return {
                'ok': True,
                'title': '未配置 server_chan_key，未发送微信',
                'location': location,
            }

    except Exception as exc:
        logger.exception('任务执行异常')
        record_error('任务执行异常', exc)
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
        config = config_store.DEFAULT_CONFIG.copy()
    else:
        config = getConfig()
    if args.dry_run:
        config['dry_run'] = True

    # 配置校验
    errors = validate_config(config)
    if args.configure or (getattr(sys, 'frozen', False) and errors):
        configured = config_gui.configure(
            config, config_store.DEFAULT_CONFIG, validate_config, _get_config_path(), errors)
        if configured is None:
            logger.error('配置未保存，程序退出')
            return
        config, should_run = configured
        if not should_run:
            logger.info('配置已保存，程序退出')
            return
        errors = validate_config(config)

    if errors:
        for err in errors:
            logger.error('配置错误: %s', err)
        logger.error('请检查 config.json 后重新运行')
        return

    remind_daily = config.get('remind_daily', False)
    remind_time = config.get('remind_time', 9)
    repeat_task = None
    if config.get('urgent_low_power_repeat'):
        repeat_task = lambda: job(config, urgent_only=True)

    # 立即尝试执行一次；若今天已成功执行过，则不会重复消耗推送额度。
    run_once_per_day(lambda: job(config), force=args.force, repeat_task=repeat_task)

    if not remind_daily:
        logger.info('未开启每日提醒，程序退出')
        return

    # 使用 schedule 安排每日定时任务
    schedule.every().day.at(f'{remind_time:02d}:00').do(
        run_once_per_day, lambda: job(config), repeat_task=repeat_task)
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
