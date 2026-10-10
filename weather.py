import logging

import requests

import net_egress

logger = logging.getLogger('electricity')

OPEN_METEO_FORECAST = 'https://api.open-meteo.com/v1/forecast'

# 深圳大学南山区校区坐标
SZU_LAT = 22.5333
SZU_LON = 113.9298


def fetch_temperature(past_days: int = 14, forecast_days: int = 1,
                      egress=None, proxy_url: str = None,
                      fallback_proxy_url: str = None,
                      timeout: float = 15) -> dict:
    """获取近期历史和当天气温，返回 {MM-DD: 最高温度}。

    天气是可选增强项：任何失败都只记一行告警并返回空字典，
    绝不阻断电量数据采集与微信推送。
    """
    past_days = max(0, min(int(past_days), 92))
    forecast_days = max(1, min(int(forecast_days), 16))
    params = {
        'latitude': SZU_LAT,
        'longitude': SZU_LON,
        'past_days': past_days,
        'forecast_days': forecast_days,
        'daily': 'temperature_2m_max',
        'timezone': 'Asia/Shanghai',
    }

    try:
        resp, used = net_egress.request(
            'GET', OPEN_METEO_FORECAST,
            params=params,
            egress=egress or net_egress.DEFAULT_SPEC,
            proxy_url=proxy_url,
            fallback_proxy_url=fallback_proxy_url,
            retries=1,
            connect_timeout=4,
            read_timeout=timeout,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning('近期气温获取失败（不影响电费推送）: %s', net_egress.short_error(exc))
        return {}

    logger.debug('气温数据来自出口 %s', used)
    dates = data.get('daily', {}).get('time', [])
    temps = data.get('daily', {}).get('temperature_2m_max', [])
    result = {
        date_str[5:]: round(temp, 1)
        for date_str, temp in zip(dates, temps)
        if temp is not None
    }

    logger.info('获取 %d 天气温数据（过去 %d 天 + 预报 %d 天）',
                len(result), past_days, forecast_days)
    return result
