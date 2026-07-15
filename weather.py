import logging

import requests

logger = logging.getLogger('electricity')

OPEN_METEO_FORECAST = 'https://api.open-meteo.com/v1/forecast'

# 深圳大学南山区校区坐标
SZU_LAT = 22.5333
SZU_LON = 113.9298

# Open-Meteo 无需代理
_session = requests.Session()
_session.trust_env = False


def fetch_temperature(past_days: int = 14, forecast_days: int = 1) -> dict:
    """获取近期历史和当天气温，返回 {MM-DD: 最高温度}。"""
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
        resp = _session.get(OPEN_METEO_FORECAST, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        logger.exception('近期气温获取失败')
        return {}

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
