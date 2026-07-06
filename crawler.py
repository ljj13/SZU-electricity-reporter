import requests
import datetime
import logging
import time
from html.parser import HTMLParser

logger = logging.getLogger('electricity')

# 重试配置
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]  # 每次重试的等待秒数（指数退避）
REQUEST_TIMEOUT = 10  # 请求超时秒数


class _ElectricityTableParser(HTMLParser):
    """提取电费系统表格中的日期与数值单元格。"""

    def __init__(self):
        super().__init__()
        self._capture = None
        self._parts = []
        self.date_cells = []
        self.value_cells = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != 'td':
            return
        attrs = {name.lower(): value for name, value in attrs}
        width = attrs.get('width')
        align = attrs.get('align', '').lower()
        if align == 'center' and width in ('13%', '22%'):
            self._capture = width
            self._parts = []

    def handle_data(self, data):
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != 'td' or not self._capture:
            return
        text = ''.join(self._parts).strip()
        if self._capture == '22%':
            self.date_cells.append(text)
        else:
            self.value_cells.append(text)
        self._capture = None
        self._parts = []


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


def parse_table_data(html: str) -> list:
    """解析电费系统 HTML，返回日期、剩余电量、总用电量、总购电量。"""
    parser = _ElectricityTableParser()
    parser.feed(html)

    rows = []
    row, p = -1, 0
    for datum in parser.value_cells:
        if p % 5 == 0:
            row += 1
            if row >= len(parser.date_cells):
                break
            rows.append([parser.date_cells[row].strip()[:10]])
        elif p % 5 != 1:
            rows[row].append(float(datum.strip()))
        p += 1

    return rows


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

    e_data = parse_table_data(html)

    logger.info('成功解析 %d 条电量记录', len(e_data))
    return e_data
