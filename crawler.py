import requests
import datetime
import logging
import re

import net_egress
from html.parser import HTMLParser

logger = logging.getLogger('electricity')

# 重试配置（校园内网，短退避）
MAX_RETRIES = 3
RETRY_BACKOFF = [3, 8]  # 每次重试前的等待秒数
CONNECT_TIMEOUT = 5    # 连接超时秒数
REQUEST_TIMEOUT = 15   # 读取超时秒数


def _mask_value(value: str) -> str:
    value = str(value)
    if len(value) <= 2:
        return '**'
    return '*' * (len(value) - 2) + value[-2:]


class _ElectricityTableParser(HTMLParser):
    """按表格行提取单元格文本，不依赖页面中的列宽样式。"""

    def __init__(self):
        super().__init__()
        self._row = None
        self._cell_parts = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == 'tr':
            self._row = []
        elif tag in ('td', 'th') and self._row is not None:
            self._cell_parts = []

    def handle_data(self, data):
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ('td', 'th') and self._cell_parts is not None:
            text = ' '.join(''.join(self._cell_parts).split())
            self._row.append(text)
            self._cell_parts = None
        elif tag == 'tr' and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """校园内网请求：强制直连出口，带有限重试与显式超时。"""
    resp, _ = net_egress.request(
        method, url,
        egress=net_egress.EGRESS_DIRECT,
        retries=MAX_RETRIES,
        backoff=RETRY_BACKOFF,
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=REQUEST_TIMEOUT,
        retry_post_read_timeout=True,
        **kwargs)
    return resp


def parse_table_data(html: str) -> list:
    """解析电费系统 HTML，返回日期、剩余电量、总用电量、总购电量。"""
    parser = _ElectricityTableParser()
    parser.feed(html)

    rows = []
    for cells in parser.rows:
        date_index = None
        date_value = None
        for index, cell in enumerate(cells):
            match = re.search(r'\d{4}-\d{2}-\d{2}', cell)
            if match:
                date_index = index
                date_value = match.group(0)
                break

        # 数据行中日期前依次为：剩余电量、总用电量、总购电量。
        if date_index is None or date_index < 3:
            continue

        try:
            values = [
                float(value.replace(',', '').strip())
                for value in cells[date_index - 3:date_index]
            ]
        except ValueError:
            logger.debug('跳过无法解析的电量数据行: %r', cells)
            continue

        rows.append([date_value, *values])

    if not rows:
        raise ValueError('电量页面中未找到有效数据行，页面结构或查询结果可能已变化')

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
                _mask_value(room_name), room_id, days_before, today)

    response = _request_with_retry('POST', url, data=params)
    html = response.text

    e_data = parse_table_data(html)

    logger.info('成功解析 %d 条电量记录', len(e_data))
    return e_data
