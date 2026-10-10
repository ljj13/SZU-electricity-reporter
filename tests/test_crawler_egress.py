"""crawler：校园内网必须强制直连，且带有限重试。"""

import unittest
from unittest import mock

import crawler

HTML = """
<table>
  <tr><td>剩余</td><td>总用电</td><td>总购电</td><td>日期</td></tr>
  <tr><td>125.56</td><td>100.0</td><td>120.0</td><td>2026-10-08</td></tr>
  <tr><td>130.04</td><td>95.0</td><td>120.0</td><td>2026-10-07</td></tr>
</table>
"""


class CrawlerEgressTests(unittest.TestCase):
    def test_crawl_forces_direct_egress(self):
        seen = {}
        resp = mock.MagicMock()
        resp.text = HTML

        def fake_request(method, url, **kwargs):
            seen['method'] = method
            seen['url'] = url
            seen['egress'] = kwargs.get('egress')
            seen['retries'] = kwargs.get('retries')
            return resp, 'direct'

        with mock.patch.object(crawler.net_egress, 'request', side_effect=fake_request):
            rows = crawler.crawlData('10.0.0.1', '101', '8092', 14)

        self.assertEqual(seen['egress'], crawler.net_egress.EGRESS_DIRECT)
        self.assertEqual(seen['url'], 'http://192.168.84.3:9090/cgcSims/selectList.do')
        self.assertEqual(seen['retries'], crawler.MAX_RETRIES)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], '2026-10-08')

    def test_parse_table_data_raises_on_empty_page(self):
        with self.assertRaises(ValueError):
            crawler.parse_table_data('<html><body>无数据</body></html>')


if __name__ == '__main__':
    unittest.main()
