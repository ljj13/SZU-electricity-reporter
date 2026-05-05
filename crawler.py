import requests
import datetime
import re
import logging
import time

logger = logging.getLogger('electricity')

# 重试配置
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]  # 每次重试的等待秒数（指数退避）
REQUEST_TIMEOUT = 10  # 请求超时秒数


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
            logger.warning('请求失败 (第%d次): %s', attempt, e)
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF[attempt - 1]
                logger.info('%d 秒后重试...', wait)
                time.sleep(wait)

    logger.error('请求 %s 已达最大重试次数 (%d)，放弃', url, MAX_RETRIES)
    raise last_exc


def crawlData(client: str, room_name: str, room_id: str, interval: int = 7) -> list:
    """返回一个 n*4 的二维数组：日期、剩余电量、总用电量、总购电量。"""
    url = 'http://192.168.84.3:9090/cgcSims/selectList.do'

    today = datetime.date.today()
    days_before = str(today - datetime.timedelta(days=interval - 1))
    today = str(today)

    params = {
        'hiddenType': '',
        'isHost': '0',
        'beginTime': days_before,
        'endTime': today,
        'type': '2',
        'client': client,
        'roomId': room_id,
        'roomName': room_name,
        'building': ''
    }

    logger.info('正在请求电量数据: 房间=%s, 楼栋=%s, 范围=%s~%s',
                room_name, room_id, days_before, today)

    response = _request_with_retry('POST', url, data=params)
    html = response.text

    # 匹配需要的表格块
    raw_e_data = re.findall(
        r'<td width="13%" align="center">(.*?)</td>', html, re.S)
    raw_date_data = re.findall(
        r'<td width="22%" align="center">(.*?)</td>', html, re.S)

    # 清洗数据
    e_data = []
    row, p = -1, 0
    for datum in raw_e_data:
        if p % 5 == 0:
            row += 1
            e_data.append([])
            e_data[row].append(raw_date_data[row].strip()[:10])
        elif p % 5 != 1:
            e_data[row].append(float(datum.strip()))
        p += 1

    logger.info('成功解析 %d 条电量记录', len(e_data))
    return e_data
