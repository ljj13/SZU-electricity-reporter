import logging
import re

import requests

import charts
import net_egress

logger = logging.getLogger('electricity')

# 默认重试配置（可被 config.json 覆盖）
MAX_RETRIES = net_egress.DEFAULT_RETRIES
REQUEST_TIMEOUT = net_egress.DEFAULT_READ_TIMEOUT


def _mask_url(url: str) -> str:
    """隐藏 URL 中的 Server酱 SendKey，避免泄露到日志。"""
    return re.sub(r'(SCT[A-Za-z0-9]{6})[A-Za-z0-9]+', r'\1***', url)


def send(key_url: str, data: dict, egress=None, proxy_url: str = None,
         fallback_proxy_url: str = None, retries: int = None,
         timeout: float = None):
    """
    使用 Server酱 Turbo 发送电量数据至微信。

    key_url 支持两种格式:
      - 新版 (推荐): sendkey，例如 "SCT123456..."
      - 旧版兼容: 完整 URL，例如 "https://sc.ftqq.com/xxx.send"

    出网方式由 ``egress`` 出口链决定（默认 proxy -> fallback -> direct），
    校园内网不经过本函数。
    """
    sendkey = _extract_sendkey(key_url)
    if key_url.startswith('http'):
        logger.info('检测到旧版 Server酱 URL，已自动转换为 Turbo API')
    url = f'https://sctapi.ftqq.com/{sendkey}.send'

    payload = {
        'title': data.get('text', '电量提醒'),
        'desp': data.get('desp', ''),
    }

    logger.info('正在推送至 Server酱 Turbo: %s', _mask_sendkey(sendkey))
    try:
        resp, used = net_egress.request(
            'POST', url,
            egress=egress or net_egress.DEFAULT_SPEC,
            proxy_url=proxy_url,
            fallback_proxy_url=fallback_proxy_url,
            retries=MAX_RETRIES if retries is None else retries,
            read_timeout=REQUEST_TIMEOUT if timeout is None else timeout,
            data=payload,
        )
    except requests.exceptions.HTTPError as exc:
        # 永久性 HTTP 错误（例如 SendKey 无效）不会重试，这里给出可读结果
        resp = exc.response
        if resp is None:
            raise
        message = ''
        try:
            message = resp.json().get('message', '')
        except ValueError:
            message = resp.text[:120]
        logger.error('Server酱返回 HTTP %s: %s', resp.status_code, message)
        return False

    logger.info('推送响应来自出口 %s (HTTP %s)', used, resp.status_code)
    try:
        result = resp.json()
    except ValueError:
        logger.error('Server酱返回非 JSON 响应: %s', resp.text[:200])
        return False

    if result.get('code') == 0:
        logger.info('Server酱推送成功')
        return True
    logger.error('Server酱推送失败: %s', result.get('message', '未知错误'))
    return False


def _extract_sendkey(key_url: str) -> str:
    if key_url.startswith('http'):
        return key_url.rstrip('/').split('/')[-1].replace('.send', '')
    return key_url


def _mask_sendkey(sendkey: str) -> str:
    if len(sendkey) <= 10:
        return '***'
    return f'{sendkey[:6]}...{sendkey[-4:]}'


def handle(data: list, describe: str, analysis_text: str = '',
           low_power_threshold: float = None) -> dict:
    """将电量数据格式化为 Server酱 消息格式，包含图表和预测。"""
    latest = data[0] if data else {}

    # ── 预测 ──
    prediction = charts.predict_usage(
        data, reserve=low_power_threshold or 0)
    if (low_power_threshold is not None
            and isinstance(latest.get('rest'), (int, float))
            and latest['rest'] <= low_power_threshold):
        text = f'剩余电量 {latest["rest"]:.2f} 度，低于 {low_power_threshold:g} 度阈值'
        predict_text = '**电量偏低，请尽快充值。**'
    elif prediction and prediction.days > 0:
        text = f'预计还有 {prediction.days} 天需要充值电费'
        range_text = (
            f'{prediction.lower_days}～{prediction.upper_days} 天'
            if prediction.lower_days != prediction.upper_days
            else f'约 {prediction.days} 天'
        )
        predict_text = (
            f'**预计还有 {prediction.days} 天需要充值电费**\n\n'
            f'按近期每天约 **{prediction.daily_usage:.1f}** 度估算，'
            f'合理范围：**{range_text}**。'
        )
    elif prediction and prediction.days == 0:
        text = '电量即将进入充值阈值，请尽快充值'
        predict_text = (
            '**电量即将进入充值阈值，请尽快充值！**\n\n'
            f'近期每天约使用 **{prediction.daily_usage:.1f}** 度。'
        )
    else:
        text = '暂无法预测充值时间'
        predict_text = '（有效日耗数据不足，暂无法预测）'

    # ── 图表 ──
    rest_chart_url = charts.build_rest_chart_url(data)
    cost_chart_url = charts.build_cost_chart_url(data)

    # ── 表格（日期、温度、用电、剩余、充电）──
    COL_ORDER = ['date', 'temp', 'cost', 'rest', 'charge']
    table_rows = ''
    for line in data:
        row = ''
        for key in COL_ORDER:
            val = line.get(key, '-')
            if isinstance(val, float):
                row += '| {:.2f} '.format(val)
            else:
                row += '| {} '.format(val)
        row += '|\n'
        table_rows += row

    # ── 拼接 desp ──
    desp = f'{describe}\n\n'
    desp += f'{predict_text}\n\n'
    desp += f'**剩余电量趋势**\n\n![剩余电量]({rest_chart_url})\n\n'
    desp += f'**每日用电量与气温**\n\n![用电量与气温]({cost_chart_url})\n\n'
    if analysis_text:
        desp += f'{analysis_text}\n\n'
    desp += '| 日期 | 温度 | 用电 | 剩余 | 充电 |\n'
    desp += '| :---: | :---: | :---: | :---: | :---: |\n'
    desp += table_rows

    return {
        'text': text,
        'desp': desp
    }
