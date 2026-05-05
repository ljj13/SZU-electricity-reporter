import logging

import requests

logger = logging.getLogger('electricity')

OPEN_METEO_ARCHIVE = 'https://archive-api.open-meteo.com/v1/archive'
OPEN_METEO_FORECAST = 'https://api.open-meteo.com/v1/forecast'

# 深圳大学南山区校区坐标
SZU_LAT = 22.5333
SZU_LON = 113.9298

# Open-Meteo 无需代理
_session = requests.Session()
_session.trust_env = False


def fetch_temperature(start_date: str, end_date: str) -> dict:
    """获取历史气温，返回 {MM-DD: 最高温度} 字典。"""
    params = {
        'latitude': SZU_LAT,
        'longitude': SZU_LON,
        'start_date': start_date,
        'end_date': end_date,
        'daily': 'temperature_2m_max',
        'timezone': 'Asia/Shanghai',
    }

    try:
        resp = _session.get(OPEN_METEO_ARCHIVE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.warning('历史气温获取失败，尝试预报接口')
        try:
            resp = _session.get(OPEN_METEO_FORECAST, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception('气温获取失败')
            return {}

    dates = data.get('daily', {}).get('time', [])
    temps = data.get('daily', {}).get('temperature_2m_max', [])

    result = {}
    for date_str, temp in zip(dates, temps):
        if temp is not None:
            result[date_str[5:]] = round(temp, 1)

    logger.info('获取 %d 天气温数据', len(result))
    return result
