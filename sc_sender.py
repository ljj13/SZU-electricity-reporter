import requests
import time
import logging

import charts

logger = logging.getLogger('electricity')

# 重试配置
MAX_RETRIES = 3
RETRY_BACKOFF = [3, 10, 20]
REQUEST_TIMEOUT = 10


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """带重试和超时的 HTTP 请求。"""
    kwargs.setdefault('timeout', REQUEST_TIMEOUT)
    last_exc = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug('HTTP %s %s (第%d次尝试)', method, url, attempt)
            resp = requests.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except (requests.RequestException, requests.HTTPError) as e:
            last_exc = e
            logger.warning('推送请求失败 (第%d次): %s', attempt, e)
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF[attempt - 1]
                logger.info('%d 秒后重试...', wait)
                time.sleep(wait)

    logger.error('推送已达最大重试次数 (%d)，放弃', MAX_RETRIES)
    raise last_exc


def send(key_url: str, data: dict):
    """
    使用 Server酱 Turbo 发送电量数据至微信。

    key_url 支持两种格式:
      - 新版 (推荐): sendkey，例如 "SCT123456..."
      - 旧版兼容: 完整 URL，例如 "https://sc.ftqq.com/xxx.send"
    """
    if key_url.startswith('http'):
        sendkey = key_url.rstrip('/').split('/')[-1].replace('.send', '')
        url = f'https://sctapi.ftqq.com/{sendkey}.send'
        logger.info('检测到旧版 Server酱 URL，已自动转换为 Turbo API')
    else:
        url = f'https://sctapi.ftqq.com/{key_url}.send'

    payload = {
        'title': data.get('text', '电量提醒'),
        'desp': data.get('desp', ''),
    }

    logger.info('正在推送至 Server酱 Turbo...')
    resp = _request_with_retry('POST', url, data=payload)
    result = resp.json()

    if result.get('code') == 0:
        logger.info('Server酱推送成功')
    else:
        logger.error('Server酱推送失败: %s', result.get('message', '未知错误'))


def handle(data: list, describe: str, analysis_text: str = '') -> dict:
    """将电量数据格式化为 Server酱 消息格式，包含图表和预测。"""
    cur_date = time.strftime("%m-%d", time.localtime())
    if data[-1]['date'] == cur_date:
        text = '昨日用电{:.2f}度，今日可用{:.2f}度'.format(
            data[-2]['cost'], data[-1]['rest'])
    else:
        text = '电量数据无更新呀'

    # ── 预测 ──
    days = charts.predict_days(data)
    if days > 0:
        predict_text = f'**预计还有 {days} 天需要充值电费**'
    elif days == 0:
        predict_text = '**电量即将耗尽，请尽快充值！**'
    else:
        predict_text = '（数据不足，暂无法预测）'

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
