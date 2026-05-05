import csv
import logging
import sys
from pathlib import Path

logger = logging.getLogger('electricity')

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else SCRIPT_DIR
CSV_FILE = APP_DIR / 'electricity_history.csv'
FIELDS = ['date', 'cost', 'rest', 'charge', 'temp']


def save(data: list):
    """将电量数据追加写入 CSV，自动去重（同一天不重复写）。"""
    existing_dates = set()
    if CSV_FILE.exists():
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_dates.add(row['date'])

    new_rows = [row for row in data if row['date'] not in existing_dates]
    if not new_rows:
        logger.info('CSV 中已包含今日数据，跳过写入')
        return

    write_header = not CSV_FILE.exists()
    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        if write_header:
            writer.writeheader()
        for row in new_rows:
            clean = {}
            for k in FIELDS:
                v = row.get(k, '')
                if isinstance(v, float):
                    clean[k] = round(v, 2)
                else:
                    clean[k] = v if v != '' else ''
            writer.writerow(clean)

    logger.info('写入 %d 条新记录到 %s', len(new_rows), CSV_FILE.name)


def update_temp(date: str, temp: float):
    """更新指定日期的气温数据。"""
    if not CSV_FILE.exists():
        return

    rows = []
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['date'] == date and not row.get('temp'):
                row['temp'] = round(temp, 1)
            rows.append(row)

    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def load() -> list:
    """读取全部历史数据，返回字典列表。"""
    if not CSV_FILE.exists():
        return []

    rows = []
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in ['cost', 'rest', 'charge', 'temp']:
                val = row.get(key, '')
                if val == '-' or val == '':
                    row[key] = '-'
                else:
                    try:
                        row[key] = float(val)
                    except ValueError:
                        pass
            rows.append(row)

    return rows
