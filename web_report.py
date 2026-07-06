import html
import re
import sys
from pathlib import Path

import charts

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else SCRIPT_DIR
REPORT_FILE = APP_DIR / 'report.html'


def write_report(data: list, describe: str, analysis_text: str = '', output_path=None) -> Path:
    """将电量结果写成本地 HTML 报告。"""
    path = Path(output_path) if output_path else REPORT_FILE
    path.write_text(render_report(data, describe, analysis_text), encoding='utf-8')
    return path


def render_report(data: list, describe: str, analysis_text: str = '') -> str:
    latest = data[0] if data else {}
    previous = data[1] if len(data) > 1 else {}
    summary = _build_summary(latest, previous)
    prediction = _build_prediction(data)
    rest_chart_url = charts.build_rest_chart_url(data) if data else ''
    cost_chart_url = charts.build_cost_chart_url(data) if data else ''
    rows = ''.join(_render_row(row) for row in data)

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(describe)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7fb;
      --panel: #ffffff;
      --ink: #1f2937;
      --muted: #667085;
      --line: #d8dee9;
      --accent: #1565c0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
      line-height: 1.55;
    }}
    header {{
      padding: 28px clamp(16px, 4vw, 48px) 18px;
      background: #ffffff;
      border-bottom: 1px solid var(--line);
    }}
    main {{
      width: min(1120px, calc(100% - 32px));
      margin: 24px auto 48px;
      display: grid;
      gap: 18px;
    }}
    h1, h2 {{ margin: 0; }}
    h1 {{ font-size: clamp(24px, 4vw, 36px); }}
    h2 {{ font-size: 18px; margin-bottom: 12px; }}
    .muted {{ color: var(--muted); }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 13px;
    }}
    .metric strong {{
      display: block;
      margin-top: 6px;
      font-size: 24px;
      color: var(--accent);
    }}
    .charts {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .chart-img {{
      width: 100%;
      min-height: 260px;
      object-fit: contain;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-variant-numeric: tabular-nums;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: center;
      white-space: nowrap;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .analysis {{
      white-space: pre-wrap;
      color: #344054;
    }}
    @media (max-width: 760px) {{
      .summary, .charts {{ grid-template-columns: 1fr; }}
      table {{ font-size: 14px; }}
      th, td {{ padding: 8px 4px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(describe)}</h1>
    <p class="muted">本地网页报告，不消耗 Server酱推送次数。</p>
  </header>
  <main>
    <div class="summary">
      <div class="metric"><span>今日可用</span><strong>{summary['rest']}</strong></div>
      <div class="metric"><span>昨日用电</span><strong>{summary['cost']}</strong></div>
      <div class="metric"><span>预计</span><strong>{prediction}</strong></div>
    </div>
    <div class="charts">
      <section>
        <h2>剩余电量趋势</h2>
        <img class="chart-img" src="{html.escape(rest_chart_url)}" alt="剩余电量趋势">
      </section>
      <section>
        <h2>每日用电量与气温</h2>
        <img class="chart-img" src="{html.escape(cost_chart_url)}" alt="每日用电量与气温">
      </section>
    </div>
    <section>
      <h2>用电规律分析</h2>
      <div class="analysis">{_format_analysis(analysis_text)}</div>
    </section>
    <section>
      <h2>历史记录</h2>
      <table>
        <thead><tr><th>日期</th><th>温度</th><th>用电</th><th>剩余</th><th>充电</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>'''


def _build_summary(latest: dict, previous: dict) -> dict:
    return {
        'rest': _format_value(latest.get('rest'), ' 度'),
        'cost': _format_value(previous.get('cost'), ' 度'),
    }


def _build_prediction(data: list) -> str:
    days = charts.predict_days(data)
    if days > 0:
        return f'{days} 天'
    if days == 0:
        return '即将耗尽'
    return '数据不足'


def _render_row(row: dict) -> str:
    cells = [
        row.get('date', '-'),
        _format_value(row.get('temp'), '°C'),
        _format_value(row.get('cost'), ' 度'),
        _format_value(row.get('rest'), ' 度'),
        _format_value(row.get('charge'), ' 度'),
    ]
    rendered = ''.join(f'<td>{html.escape(str(cell))}</td>' for cell in cells)
    return f'<tr>{rendered}</tr>'


def _format_value(value, suffix: str = '') -> str:
    if isinstance(value, (int, float)):
        return f'{value:.2f}{suffix}'
    if value in (None, ''):
        return '-'
    return str(value)


def _format_analysis(text: str) -> str:
    if not text:
        return '暂无分析数据'
    cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    return html.escape(cleaned)
