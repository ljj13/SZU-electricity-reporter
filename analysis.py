import datetime
import logging

import numpy as np
import data_store

logger = logging.getLogger('electricity')


def _parse_date(mm_dd: str) -> datetime.date:
    """将 YYYY-MM-DD 或 MM-DD 格式转为完整日期。"""
    if len(mm_dd) >= 10 and mm_dd[4] == '-' and mm_dd[7] == '-':
        return datetime.date.fromisoformat(mm_dd[:10])

    month, day = map(int, mm_dd.split('-'))
    today = datetime.date.today()
    year = today.year
    if month > today.month:
        year -= 1
    return datetime.date(year, month, day)


def analyze() -> str:
    """分析历史用电数据，返回格式化文本。"""
    rows = data_store.load()

    valid = [r for r in rows if isinstance(r['cost'], (int, float)) and r['cost'] != '-']
    if len(valid) < 3:
        return '（历史数据不足，暂无法分析）'

    lines = ['**用电规律分析**\n']

    # ── 周末 vs 工作日 ──
    weekday_costs = []
    weekend_costs = []
    for row in valid:
        try:
            dt = _parse_date(row['date'])
            if dt.weekday() < 5:
                weekday_costs.append(row['cost'])
            else:
                weekend_costs.append(row['cost'])
        except (ValueError, AttributeError):
            continue

    if weekday_costs and weekend_costs:
        avg_wd = sum(weekday_costs) / len(weekday_costs)
        avg_we = sum(weekend_costs) / len(weekend_costs)
        diff = avg_we - avg_wd
        if diff > 1:
            lines.append(f'- 周末比工作日多用 **{diff:.1f}** 度/天（周末 {avg_we:.1f} vs 工作日 {avg_wd:.1f}）')
        elif diff < -1:
            lines.append(f'- 工作日比周末多用 **{-diff:.1f}** 度/天（工作日 {avg_wd:.1f} vs 周末 {avg_we:.1f}）')
        else:
            lines.append(f'- 周末与工作日用电接近（工作日 {avg_wd:.1f}，周末 {avg_we:.1f}）')

    # ── 最近 7 天均值 ──
    recent = valid[:7]
    avg_7 = sum(r['cost'] for r in recent) / len(recent)
    lines.append(f'- 最近 {len(recent)} 天平均用电 **{avg_7:.1f}** 度/天')

    # ── 用电最高/最低日 ──
    max_row = max(valid, key=lambda r: r['cost'])
    min_row = min(valid, key=lambda r: r['cost'])
    lines.append(f'- 用电最高：{max_row["date"]}（{max_row["cost"]:.1f} 度）')
    lines.append(f'- 用电最低：{min_row["date"]}（{min_row["cost"]:.1f} 度）')

    # ── 月度汇总 ──
    monthly = {}
    for row in valid:
        try:
            dt = _parse_date(row['date'])
            key = dt.strftime('%Y-%m')
            monthly[key] = monthly.get(key, 0) + row['cost']
        except (ValueError, AttributeError):
            continue

    if len(monthly) >= 2:
        months = sorted(monthly.items())
        cur_month = months[-1]
        prev_month = months[-2]
        lines.append(f'- {cur_month[0]} 累计用电 **{cur_month[1]:.1f}** 度，{prev_month[0]} 为 {prev_month[1]:.1f} 度')

    # ── 气温与用电相关性 ──
    temp_rows = [r for r in valid
                 if isinstance(r.get('temp'), (int, float)) and r['temp'] != '-']
    if len(temp_rows) >= 3:
        temps = np.array([r['temp'] for r in temp_rows], dtype=float)
        costs = np.array([r['cost'] for r in temp_rows], dtype=float)
        corr = np.corrcoef(temps, costs)[0, 1]

        lines.append('')
        if corr > 0.3:
            lines.append(f'- 气温与用电正相关（r={corr:.2f}），气温越高用电越多')
        elif corr < -0.3:
            lines.append(f'- 气温与用电负相关（r={corr:.2f}），气温越高用电越少')
        else:
            lines.append(f'- 气温与用电相关性较弱（r={corr:.2f}）')

        # 高温 vs 凉爽日对比
        hot = [r for r in temp_rows if r['temp'] >= 30]
        cool = [r for r in temp_rows if r['temp'] < 25]
        if hot and cool:
            avg_hot = sum(r['cost'] for r in hot) / len(hot)
            avg_cool = sum(r['cost'] for r in cool) / len(cool)
            diff = avg_hot - avg_cool
            if diff > 1:
                lines.append(f'- 高温日（≥30°C）比凉爽日（<25°C）多用 **{diff:.1f}** 度/天（{avg_hot:.1f} vs {avg_cool:.1f}）')
            elif diff < -1:
                lines.append(f'- 凉爽日比高温日多用 **{-diff:.1f}** 度/天（{avg_cool:.1f} vs {avg_hot:.1f}）')

    return '\n'.join(lines)
