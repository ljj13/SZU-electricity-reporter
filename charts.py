import json
import urllib.parse
import logging

import numpy as np

logger = logging.getLogger('electricity')

QUICKCHART_BASE = 'https://quickchart.io/chart?c='


def predict_days(data: list) -> int:
    """线性回归预测剩余电量还能用几天。data 最新在前。"""
    valid = [row for row in data if isinstance(row['rest'], (int, float))]
    if len(valid) < 2:
        return -1

    ordered = list(reversed(valid))

    last_charge_idx = 0
    for i in range(1, len(ordered)):
        if ordered[i]['rest'] > ordered[i - 1]['rest'] + 10:
            last_charge_idx = i

    after_charge = ordered[last_charge_idx:]
    if len(after_charge) < 2:
        return -1

    rest_values = np.array([row['rest'] for row in after_charge], dtype=float)
    x = np.arange(len(rest_values))
    a, b = np.polyfit(x, rest_values, 1)

    if a >= 0:
        return -1

    days_from_start = -b / a
    days_remaining = days_from_start - (len(rest_values) - 1)

    return max(0, int(days_remaining))


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
