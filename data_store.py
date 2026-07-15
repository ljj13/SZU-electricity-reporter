import csv
import datetime
import logging
import sys
from pathlib import Path

logger = logging.getLogger('electricity')

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else SCRIPT_DIR
CSV_FILE = APP_DIR / 'electricity_history.csv'
FIELDS = ['date', 'cost', 'rest', 'charge', 'temp']


def save(data: list):
    """将电量数据写入 CSV；已有日期用新数据补全，缺失日期追加。"""
    existing_rows = []
    rows_by_date = {}
    if CSV_FILE.exists():
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['date'] = normalize_date(row.get('date', ''))
                existing_rows.append(row)
                rows_by_date[row['date']] = row

    added = 0
    updated = 0
    for row in data:
        date = row.get('date')
        if not date:
            continue
        clean = _clean_row(row)
        date = clean['date']
        existing = rows_by_date.get(date)
        if existing is None:
            existing_rows.append(clean)
            rows_by_date[date] = clean
            added += 1
            continue
        if _merge_row(existing, clean):
            updated += 1

    if added == 0 and updated == 0:
        logger.info('CSV 中已包含最新数据，跳过写入')
        return

    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        for row in existing_rows:
            writer.writerow({k: row.get(k, '') for k in FIELDS})

    logger.info('CSV 已新增 %d 条、更新 %d 条: %s', added, updated, CSV_FILE.name)


def _clean_row(row: dict) -> dict:
    clean = {}
    for k in FIELDS:
        v = row.get(k, '')
        if k == 'date':
            clean[k] = normalize_date(v)
        elif isinstance(v, float):
            clean[k] = str(round(v, 2))
        else:
            clean[k] = v if v != '' else ''
    return clean


def normalize_date(date_str: str, today: datetime.date = None) -> str:
    """将 YYYY-MM-DD 或 MM-DD 日期归一化为 YYYY-MM-DD。"""
    date_str = str(date_str).strip()
    if not date_str:
        return ''
    if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
        return date_str[:10]

    month, day = map(int, date_str[:5].split('-'))
    today = today or datetime.date.today()
    year = today.year
    if month > today.month:
        year -= 1
    return f'{year:04d}-{month:02d}-{day:02d}'


def same_day(left: str, right: str) -> bool:
    """比较日期，兼容旧 MM-DD 与新 YYYY-MM-DD。"""
    return normalize_date(left) == normalize_date(right)


def _merge_row(existing: dict, incoming: dict) -> bool:
    changed = False
    for key in FIELDS:
        old = existing.get(key, '')
        new = incoming.get(key, '')
        if new not in ('', '-') and old != new:
            existing[key] = new
            changed = True
    return changed


def update_temperatures(temperatures: dict) -> int:
    """批量补全气温数据，只读取和写入 CSV 一次。"""
    if not CSV_FILE.exists() or not temperatures:
        return 0

    rows = []
    updated = 0
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['date'] = normalize_date(row.get('date', ''))
            date_key = row['date'][5:] if len(row['date']) >= 10 else row['date']
            temp = temperatures.get(row['date'], temperatures.get(date_key))
            if temp is not None and row.get('temp') in ('', '-', None):
                row['temp'] = round(float(temp), 1)
                updated += 1
            rows.append(row)

    if updated == 0:
        return 0

    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    logger.info('批量补全 %d 条气温数据', updated)
    return updated


def update_temp(date: str, temp: float):
    """兼容旧调用：更新单日气温。"""
    return update_temperatures({date: temp})


def load() -> list:
    """读取全部历史数据，返回字典列表。"""
    if not CSV_FILE.exists():
        return []

    rows = []
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['date'] = normalize_date(row.get('date', ''))
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
