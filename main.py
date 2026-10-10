import crawler
import sc_sender
import data_store
import analysis
import weather
import config_gui
import buildings
import config_store
import net_egress

import logging
from logging.handlers import TimedRotatingFileHandler
import argparse
import datetime
import json
import os
import re
import signal
import socket
import sys
import traceback
from pathlib import Path

import requests

import schedule
import time


def _ensure_stdio_encoding():
    """兼顾非中文 Windows 环境（如英文 Windows / CI 中的 cp1252 终端）：
    当标准流编码无法表达中文时，平滑重配置为 UTF-8，避免输出帮助文本或日志时触发 UnicodeEncodeError。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, 'reconfigure'):
            try:
                if stream.encoding:
                    try:
                        '中文'.encode(stream.encoding)
                    except (UnicodeEncodeError, LookupError):
                        stream.reconfigure(encoding='utf-8')
                else:
                    stream.reconfigure(encoding='utf-8')
            except Exception:
                pass


_ensure_stdio_encoding()

# ── 日志配置 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
# exe 模式下用 exe 所在目录，否则用脚本所在目录
# SZU_REPORTER_DIR 仅供自动化测试重定向运行目录，生产环境不设置。
_env_dir = os.environ.get('SZU_REPORTER_DIR')
APP_DIR = (Path(_env_dir) if _env_dir else
           (Path(sys.executable).parent if getattr(sys, 'frozen', False) else SCRIPT_DIR))
LOG_FILE = APP_DIR / 'electricity.log'
RUN_STATE_FILE = APP_DIR / 'last_success_date.txt'
LAST_ERROR_FILE = APP_DIR / 'last_error.txt'
RESOLVED_ERROR_FILE = APP_DIR / 'last_error.resolved.txt'
INSTANCE_LOCK_FILE = APP_DIR / '.electricity.lock'

# ── 退出码（供 cron 判定）────────────────────────────────
EXIT_OK = 0             # 成功或今日已成功（含 dry-run）
EXIT_TASK_FAILED = 1    # 采集/推送任务失败
EXIT_CONFIG = 2         # 配置缺失或非法
EXIT_PUSH_FAILED = 3    # --test-push 推送失败

logger = logging.getLogger('electricity')
logger.setLevel(logging.DEBUG)

# 控制台 handler（cron 用 --quiet 关闭，避免依赖 stdout 管道）
_console_handler = None
if sys.stdout:
    _console_handler = logging.StreamHandler(sys.stdout)
    _console_handler.setLevel(logging.INFO)
    _console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    logger.addHandler(_console_handler)

# 文件 handler（按天轮转，保留 7 天）
_fh = TimedRotatingFileHandler(LOG_FILE, when='midnight', backupCount=7, encoding='utf-8')
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
_fh.suffix = '%Y-%m-%d'
logger.addHandler(_fh)


def _disable_console_logging():
    """--quiet：移除 stdout handler，cron 下不再依赖管道输出。"""
    global _console_handler
    if _console_handler is not None:
        logger.removeHandler(_console_handler)
        _console_handler = None


class ConfigError(Exception):
    """配置缺失或不可读。"""


# ── 全局标志 ─────────────────────────────────────────────
_running = True


_instance_lock_handle = None


def acquire_single_instance_lock() -> bool:
    """Acquire an OS-backed lock so concurrent triggers cannot both send."""
    global _instance_lock_handle
    handle = open(INSTANCE_LOCK_FILE, 'a+b')
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'\0')
            handle.flush()
        handle.seek(0)

        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False

    _instance_lock_handle = handle
    return True


def release_single_instance_lock():
    global _instance_lock_handle
    handle = _instance_lock_handle
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
        _instance_lock_handle = None


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
        raise ConfigError(f'缺少配置文件: {config_path}')
    return config_store.read_config(config_path)


def validate_config(config: dict) -> list:
    """校验配置参数，返回错误列表（空列表表示全部通过）。"""
    return config_store.validate_config(config)


def egress_options(config: dict) -> dict:
    """从配置中提取网络出口参数，供各模块使用。"""
    return {
        'server_chan_egress': config.get('server_chan_egress', net_egress.DEFAULT_SPEC),
        'weather_egress': config.get('weather_egress', net_egress.DEFAULT_SPEC),
        'proxy_url': config.get('proxy_url', net_egress.DEFAULT_PROXY_URL),
        'proxy_fallback_url': config.get('proxy_fallback_url',
                                         net_egress.DEFAULT_FALLBACK_PROXY_URL),
        'push_retries': config.get('push_retries', net_egress.DEFAULT_RETRIES),
        'push_timeout': config.get('push_timeout', net_egress.DEFAULT_READ_TIMEOUT),
    }


def log_egress_summary(config: dict):
    opts = egress_options(config)
    logger.info('网络出口：内网=direct(强制) | Server酱=%s | 天气=%s',
                net_egress.describe(opts['server_chan_egress'], opts['proxy_url'],
                                    opts['proxy_fallback_url']),
                net_egress.describe(opts['weather_egress'], opts['proxy_url'],
                                    opts['proxy_fallback_url']))


def _atomic_write_text(path: Path, text: str):
    """原子写文件，避免掉电/中断产生半截状态文件。"""
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def record_error(message: str, exc: BaseException = None):
    """Write the latest user-visible failure to last_error.txt."""
    def _mask_secret(text: str) -> str:
        return re.sub(r'(SCT[A-Za-z0-9]{6})[A-Za-z0-9]+', r'\1***', text)

    lines = [
        f'time: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'error: {_mask_secret(message)}',
    ]
    if exc:
        lines.append('')
        lines.append('traceback:')
        lines.append(_mask_secret(
            ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))))
    _atomic_write_text(LAST_ERROR_FILE, '\n'.join(lines))


def clear_error():
    """成功一次后归档上一次的失败记录（保留证据，同时清空“当前故障”信号）。"""
    if LAST_ERROR_FILE.exists():
        try:
            os.replace(LAST_ERROR_FILE, RESOLVED_ERROR_FILE)
        except OSError:
            pass


def _read_run_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        text = state_path.read_text(encoding='utf-8').strip()
    except OSError:
        return {}
    if not text:
        return {}
    if text.startswith('{'):
        try:
            return json.loads(text)
        except ValueError:
            logger.warning('状态文件损坏，按未执行处理: %s', state_path)
            return {}
    return {'date': text}


def _write_run_state(state_path: Path, today: str, info: dict = None):
    state = {
        'date': today,
        'sent_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'ok': True,
    }
    if info:
        state.update({k: v for k, v in info.items() if k != 'update_state'})
    _atomic_write_text(Path(state_path), json.dumps(state, ensure_ascii=False, indent=2) + '\n')


def already_done_today(today: str = None, state_path: Path = RUN_STATE_FILE) -> bool:
    today = today or str(datetime.date.today())
    state = _read_run_state(Path(state_path))
    return state.get('date') == today


def _task_success(result) -> bool:
    if isinstance(result, dict):
        return bool(result.get('ok'))
    return bool(result)


def _should_record(result) -> bool:
    """dry-run 等“不算成功推送”的结果不占用当天名额，正式推送仍会执行。"""
    if not _task_success(result):
        return False
    if isinstance(result, dict):
        return bool(result.get('update_state', True))
    return True


def run_once_per_day(task, today: str = None, state_path: Path = RUN_STATE_FILE,
                     force: bool = False) -> str:
    """同一天最多执行一次成功推送；失败不占用当天名额。

    返回 ``skipped`` / ``success`` / ``failed``。
    """
    today = today or str(datetime.date.today())
    state_path = Path(state_path)

    if not force and already_done_today(today, state_path):
        logger.info('今日任务已成功执行过，跳过本次触发')
        return 'skipped'

    try:
        result = task()
    except Exception as exc:  # 兜底：任务异常绝不允许终止进程或吞掉退出码
        logger.exception('任务执行异常')
        record_error('任务执行异常', exc)
        return 'failed'

    if not _task_success(result):
        return 'failed'

    if _should_record(result):
        info = result if isinstance(result, dict) else {}
        _write_run_state(state_path, today, info)
        clear_error()
    return 'success'


# ── 核心任务 ─────────────────────────────────────────────
def job(config: dict = None):
    """执行一次电量查询 + 推送，带异常保护，不会因单次失败退出整个程序。"""
    try:
        config = config or getConfig()
        room_name = config['room_name']
        room_id = config['room_id']
        client = config['client']
        opts = egress_options(config)

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

        # 获得数据（校园内网强制直连）
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

        # 保存到 CSV（失败只告警，不影响推送）
        try:
            data_store.save(data)
        except Exception:
            logger.warning('CSV 写入失败，已跳过（不影响电费推送）', exc_info=True)

        # 天气为可选增强项：任何失败都不得阻止推送
        temp_map = {}
        try:
            temp_map = weather.fetch_temperature(
                past_days=interval_day, forecast_days=1,
                egress=opts['weather_egress'],
                proxy_url=opts['proxy_url'],
                fallback_proxy_url=opts['proxy_fallback_url'],
                timeout=opts['push_timeout'])
            data_store.update_temperatures(temp_map)
        except Exception:
            logger.warning('气温数据处理异常，已跳过（不影响电费推送）', exc_info=True)
        for row in data:
            mm_dd = row['date']
            if mm_dd in temp_map:
                row['temp'] = temp_map[mm_dd]
        logger.info('气温数据更新完成')

        # 用电规律分析（同样不阻断推送）
        try:
            analysis_text = analysis.analyze()
        except Exception:
            logger.warning('用电规律分析失败，已省略该段（不影响电费推送）', exc_info=True)
            analysis_text = ''
        logger.info('分析完成')

        location = f'{building}{room_name}' if building else room_name
        describe = f'{location}电量查询'

        if dry_run:
            logger.info('dry_run=true，已跳过微信推送')
            return {
                'ok': True,
                'update_state': False,
                'title': 'dry_run，未发送微信',
                'location': location,
            }
        elif sc_key:
            send_msg = sc_sender.handle(
                data, describe, analysis_text,
                low_power_threshold=low_power_threshold)
            try:
                sent = sc_sender.send(
                    key_url=sc_key, data=send_msg,
                    egress=opts['server_chan_egress'],
                    proxy_url=opts['proxy_url'],
                    fallback_proxy_url=opts['proxy_fallback_url'],
                    retries=opts['push_retries'],
                    timeout=opts['push_timeout'])
            except requests.RequestException as exc:
                message = '推送网络失败：所有出口均不可用 (%s)' % net_egress.short_error(exc)
                logger.error(message)
                record_error(message, exc)
                return False
            if not sent:
                record_error('Server酱推送失败，请查看 electricity.log')
                return False
            logger.info('已发送至微信')
            return {
                'ok': True,
                'title': send_msg.get('text', ''),
                'location': location,
            }
        else:
            logger.info('未配置 server_chan_key，跳过微信推送')
            return {
                'ok': True,
                'update_state': False,
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


def run_test_push(config: dict) -> int:
    """受控连通性测试：只发一条明确标注的测试消息，绝不写入 last_success_date.txt。"""
    sc_key = (config.get('server_chan_key') or '').strip()
    if not sc_key:
        logger.error('未配置 server_chan_key，无法进行测试推送')
        return EXIT_CONFIG

    opts = egress_options(config)
    building = buildings.get_building_name(config.get('room_id', ''))
    room = config.get('room_name', '')
    location = f'{building}{room}' if building else room
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = 'unknown'

    payload = {
        'text': '【测试】电费推送链路连通性测试',
        'desp': (
            '这是一条**人工触发的链路测试消息，不是当日电费日报**。\n\n'
            f'- 触发时间：{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n'
            f'- 设备：{hostname}\n'
            f'- 位置：{location or "-"}\n'
            f'- 出口链：{net_egress.describe(opts["server_chan_egress"], opts["proxy_url"], opts["proxy_fallback_url"])}\n\n'
            '收到本消息说明 Server酱 推送链路正常；当日正式日报仍会按 09:00 定时任务发送。'
        ),
    }

    logger.info('开始测试推送（不写入 last_success_date.txt，不影响当日日报）')
    try:
        ok = sc_sender.send(
            key_url=sc_key, data=payload,
            egress=opts['server_chan_egress'],
            proxy_url=opts['proxy_url'],
            fallback_proxy_url=opts['proxy_fallback_url'],
            retries=opts['push_retries'],
            timeout=opts['push_timeout'])
    except requests.RequestException as exc:
        logger.error('测试推送失败: %s', net_egress.short_error(exc))
        return EXIT_PUSH_FAILED
    if not ok:
        logger.error('测试推送失败（Server酱返回错误）')
        return EXIT_PUSH_FAILED
    logger.info('测试推送成功')
    return EXIT_OK


# ── 主入口 ───────────────────────────────────────────────
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='SZU 宿舍电量微信提醒')
    parser.add_argument('--force', action='store_true',
                        help='忽略今天已成功执行记录，强制运行一次')
    parser.add_argument('--dry-run', action='store_true',
                        help='本次只抓取和保存，不发送微信')
    parser.add_argument('--configure', action='store_true',
                        help='打开配置窗口并保存 config.json')
    parser.add_argument('--once', action='store_true',
                        help='执行一次后退出，供 Windows 任务计划程序调用')
    parser.add_argument('--test-push', action='store_true',
                        help='只发送一条标注为测试的消息，不写状态、不影响当日日报')
    parser.add_argument('--quiet', action='store_true',
                        help='不输出到 stdout（cron 使用，日志仍写入 electricity.log）')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.quiet:
        _disable_console_logging()

    try:
        config_path = _get_config_path()
        if args.configure and not config_path.exists():
            config = config_store.DEFAULT_CONFIG.copy()
        else:
            config = getConfig()
    except ConfigError as exc:
        logger.error('配置不可用: %s', exc)
        return EXIT_CONFIG

    if args.dry_run:
        config['dry_run'] = True

    # 配置校验
    errors = validate_config(config)
    if args.configure or (getattr(sys, 'frozen', False) and errors):
        configured = config_gui.configure(
            config, config_store.DEFAULT_CONFIG, validate_config, _get_config_path(), errors)
        if configured is None:
            logger.error('配置未保存，程序退出')
            return EXIT_CONFIG
        config, should_run = configured
        if not should_run:
            logger.info('配置已保存，程序退出')
            return EXIT_OK
        errors = validate_config(config)

    if errors:
        for err in errors:
            logger.error('配置错误: %s', err)
        logger.error('请检查 config.json 后重新运行')
        return EXIT_CONFIG

    log_egress_summary(config)

    if args.test_push:
        return run_test_push(config)

    remind_daily = config.get('remind_daily', False)
    remind_time = config.get('remind_time', 9)
    # 所有触发器共用同一成功状态，每天最多成功推送一次。
    status = run_once_per_day(lambda: job(config), force=args.force)
    logger.info('本次运行结果: %s', status)

    if args.once:
        logger.info('单次任务处理完成，程序退出')
        return EXIT_OK if status in ('success', 'skipped') else EXIT_TASK_FAILED

    if not remind_daily:
        logger.info('未开启每日提醒，程序退出')
        return EXIT_OK if status in ('success', 'skipped') else EXIT_TASK_FAILED

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
    return EXIT_OK


if __name__ == '__main__':
    if not acquire_single_instance_lock():
        logger.info('已有一个电量提醒任务正在运行，本次触发退出')
        sys.exit(EXIT_OK)
    else:
        try:
            sys.exit(main())
        finally:
            release_single_instance_lock()
