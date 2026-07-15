import datetime
import json
import logging
import math
import statistics
import urllib.parse
from dataclasses import dataclass


logger = logging.getLogger('electricity')

QUICKCHART_BASE = 'https://quickchart.io/chart?c='


@dataclass(frozen=True)
class UsagePrediction:
    days: int
    daily_usage: float
    lower_days: int
    upper_days: int
    sample_days: int


def _parse_date(value: str) -> datetime.date:
    value = str(value).strip()
    if len(value) >= 10 and value[4] == '-' and value[7] == '-':
        return datetime.date.fromisoformat(value[:10])

    month, day = map(int, value[:5].split('-'))
    today = datetime.date.today()
    year = today.year - (1 if month > today.month else 0)
    return datetime.date(year, month, day)


def predict_usage(data: list, reserve: float = 0, max_samples: int = 7):
    """用最近一次充值后的真实日耗中位数预测充值时间。"""
    records = []
    for row in data:
        if not isinstance(row.get('rest'), (int, float)):
            continue
        try:
            date = _parse_date(row.get('date', ''))
        except (TypeError, ValueError):
            continue
        records.append({
            'date': date,
            'rest': float(row['rest']),
            'charge': row.get('charge'),
        })

    records.sort(key=lambda item: item['date'])
    if len(records) < 2:
        return None

    # charge 记录在充值发生前一日；剩余电量明显上升作为兼容判断。
    start_index = 0
    for index in range(len(records) - 1):
        current = records[index]
        following = records[index + 1]
        explicit_charge = (
            isinstance(current['charge'], (int, float))
            and current['charge'] > 0
        )
        rest_jump = following['rest'] > current['rest'] + 10
        if explicit_charge or rest_jump:
            start_index = index + 1

    after_charge = records[start_index:]
    daily_rates = []
    for previous, current in zip(after_charge, after_charge[1:]):
        elapsed_days = (current['date'] - previous['date']).days
        if elapsed_days <= 0:
            continue
        daily_usage = (previous['rest'] - current['rest']) / elapsed_days
        if daily_usage > 0:
            daily_rates.append(daily_usage)

    daily_rates = daily_rates[-max(2, max_samples):]
    if len(daily_rates) < 2:
        return None

    median_usage = statistics.median(daily_rates)
    deviations = [abs(value - median_usage) for value in daily_rates]
    mad = statistics.median(deviations)
    if mad > 0:
        robust_limit = max(3 * 1.4826 * mad, median_usage * 0.35)
        filtered = [
            value for value in daily_rates
            if abs(value - median_usage) <= robust_limit
        ]
        if len(filtered) >= 2:
            daily_rates = filtered
            median_usage = statistics.median(daily_rates)
            deviations = [abs(value - median_usage) for value in daily_rates]
            mad = statistics.median(deviations)

    if median_usage <= 0:
        return None

    current_rest = records[-1]['rest']
    usable_power = max(0.0, current_rest - max(0.0, float(reserve or 0)))
    estimated_days = usable_power / median_usage

    # 至少保留 15% 波动，避免样本很接近时给出虚假的精确范围。
    spread = max(1.4826 * mad, median_usage * 0.15)
    low_usage = max(0.1, median_usage - spread)
    high_usage = median_usage + spread
    lower_days = max(0, math.floor(usable_power / high_usage))
    upper_days = max(lower_days, math.ceil(usable_power / low_usage))
    days = max(lower_days, min(upper_days, int(round(estimated_days))))

    return UsagePrediction(
        days=days,
        daily_usage=round(median_usage, 2),
        lower_days=lower_days,
        upper_days=upper_days,
        sample_days=len(daily_rates),
    )


def predict_days(data: list, reserve: float = 0) -> int:
    """兼容旧调用，只返回预计天数。"""
    prediction = predict_usage(data, reserve=reserve)
    return prediction.days if prediction else -1


def _build_chart_url(labels: list, dataset_label: str, values: list,
                     color: str, title: str, y_min: float, y_max: float) -> str:
    """构建 QuickChart 折线图 URL。"""
    config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": dataset_label,
                "data": values,
                "borderColor": color,
                "backgroundColor": color + "33",
                "fill": True,
                "tension": 0.3,
                "pointRadius": 4
            }]
        },
        "options": {
            "layout": {"padding": {"top": 24, "left": 8, "right": 8}},
            "title": {"display": True, "text": title, "fontColor": "#333",
                      "fontSize": 16},
            "legend": {"labels": {"fontColor": "#333"}},
            "scales": {
                "xAxes": [{"ticks": {"fontColor": "#333"},
                           "gridLines": {"color": "#ddd"}}],
                "yAxes": [{"ticks": {"fontColor": "#333", "min": y_min, "max": y_max},
                           "gridLines": {"color": "#ddd"}}]
            }
        }
    }

    encoded = urllib.parse.quote(json.dumps(config, ensure_ascii=False))
    return QUICKCHART_BASE + encoded


def _calc_range(values: list, padding_ratio: float = 0.1) -> tuple:
    """根据数据自动计算 Y 轴范围，带上下 padding。"""
    vmin, vmax = min(values), max(values)
    span = vmax - vmin
    padding = span * padding_ratio if span > 0 else 10
    y_min = max(0, vmin - padding)
    y_max = vmax + padding
    return round(y_min, 1), round(y_max, 1)


def build_rest_chart_url(data: list) -> str:
    """生成剩余电量折线图，Y 轴自适应。"""
    ordered = list(reversed(data))
    labels = [row['date'] for row in ordered]
    values = [row['rest'] for row in ordered]
    y_min, y_max = _calc_range(values, padding_ratio=0.2)
    return _build_chart_url(labels, '剩余电量(度)', values, '#4FC3F7', '剩余电量趋势', y_min, y_max)


def build_cost_chart_url(data: list) -> str:
    """生成用电量+气温双轴折线图。"""
    ordered = list(reversed(data))

    # 过滤有用电数据的行
    filtered = [row for row in ordered if isinstance(row['cost'], (int, float))]
    labels = [row['date'] for row in filtered]
    cost_values = [row['cost'] for row in filtered]
    temp_values = [row.get('temp', None) for row in filtered]

    # 计算用电量 Y 轴范围
    cost_min, cost_max = _calc_range(cost_values)

    config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "用电量(度)",
                    "data": cost_values,
                    "borderColor": "#FF7043",
                    "backgroundColor": "#FF704333",
                    "fill": True,
                    "tension": 0.3,
                    "pointRadius": 4,
                    "yAxisID": "y-cost"
                },
                {
                    "label": "气温(°C)",
                    "data": temp_values,
                    "borderColor": "#66BB6A",
                    "backgroundColor": "#66BB6A33",
                    "fill": False,
                    "tension": 0.3,
                    "pointRadius": 4,
                    "borderDash": [5, 5],
                    "yAxisID": "y-temp"
                }
            ]
        },
        "options": {
            "title": {"display": True, "text": "每日用电量与气温",
                      "fontColor": "#333", "fontSize": 16},
            "legend": {"labels": {"fontColor": "#333"}},
            "scales": {
                "xAxes": [{"ticks": {"fontColor": "#333"},
                           "gridLines": {"color": "#ddd"}}],
                "yAxes": [
                    {
                        "id": "y-cost",
                        "position": "left",
                        "ticks": {"fontColor": "#FF7043",
                                  "min": cost_min, "max": cost_max},
                        "gridLines": {"color": "#ddd"}
                    },
                    {
                        "id": "y-temp",
                        "position": "right",
                        "ticks": {"fontColor": "#66BB6A"},
                        "gridLines": {"drawOnChartArea": False}
                    }
                ]
            }
        }
    }

    encoded = urllib.parse.quote(json.dumps(config, ensure_ascii=False))
    return QUICKCHART_BASE + encoded
