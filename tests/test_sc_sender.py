"""sc_sender：出口传递、错误处理与消息格式保持不变。"""

import unittest
from unittest import mock

import requests

import sc_sender


class SendEgressTests(unittest.TestCase):
    def test_send_passes_configured_egress(self):
        seen = {}
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'code': 0}

        def fake_request(method, url, **kwargs):
            seen.update(kwargs)
            seen['method'] = method
            return resp, 'proxy'

        with mock.patch.object(sc_sender.net_egress, 'request', side_effect=fake_request):
            ok = sc_sender.send('SCT123456abcdef',
                                {'text': '标题', 'desp': '正文'},
                                egress='proxy,fallback,direct',
                                proxy_url='http://127.0.0.1:7899',
                                fallback_proxy_url='http://127.0.0.1:7890',
                                retries=2, timeout=20)

        self.assertTrue(ok)
        self.assertEqual(seen['egress'], 'proxy,fallback,direct')
        self.assertEqual(seen['proxy_url'], 'http://127.0.0.1:7899')
        self.assertEqual(seen['retries'], 2)
        self.assertEqual(seen['read_timeout'], 20)
        self.assertEqual(seen['data']['title'], '标题')
        self.assertEqual(seen['method'], 'POST')

    def test_send_defaults_to_proxy_chain(self):
        seen = {}
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'code': 0}

        def fake_request(method, url, **kwargs):
            seen.update(kwargs)
            return resp, 'proxy'

        with mock.patch.object(sc_sender.net_egress, 'request', side_effect=fake_request):
            sc_sender.send('SCT123456abcdef', {'text': 't', 'desp': 'd'})
        self.assertEqual(seen['egress'], sc_sender.net_egress.DEFAULT_SPEC)

    def test_api_error_returns_false(self):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {'code': 40001, 'message': 'bad key'}
        with mock.patch.object(sc_sender.net_egress, 'request',
                               return_value=(resp, 'proxy')):
            self.assertFalse(sc_sender.send('SCT123456abcdef', {'text': 't', 'desp': 'd'}))

    def test_non_json_response_returns_false(self):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError('not json')
        resp.text = '<html>error</html>'
        with mock.patch.object(sc_sender.net_egress, 'request',
                               return_value=(resp, 'proxy')):
            self.assertFalse(sc_sender.send('SCT123456abcdef', {'text': 't', 'desp': 'd'}))

    def test_permanent_http_error_returns_false(self):
        resp = mock.MagicMock()
        resp.status_code = 400
        resp.json.return_value = {'message': 'title 不能为空'}
        error = requests.exceptions.HTTPError('400', response=resp)
        with mock.patch.object(sc_sender.net_egress, 'request', side_effect=error):
            self.assertFalse(sc_sender.send('SCT123456abcdef', {'text': 't', 'desp': 'd'}))

    def test_transport_error_propagates(self):
        with mock.patch.object(sc_sender.net_egress, 'request',
                               side_effect=requests.exceptions.ConnectionError('down')):
            with self.assertRaises(requests.exceptions.ConnectionError):
                sc_sender.send('SCT123456abcdef', {'text': 't', 'desp': 'd'})

    def test_sendkey_is_masked_in_url(self):
        self.assertEqual(sc_sender._mask_url('https://sctapi.ftqq.com/SCT123456abcdef.send'),
                         'https://sctapi.ftqq.com/SCT123456***.send')
        self.assertEqual(sc_sender._mask_sendkey('SCT123456abcdef'), 'SCT123...cdef')


class MessageFormatTests(unittest.TestCase):
    def setUp(self):
        self.data = [
            {'date': '10-08', 'temp': 30.0, 'cost': 5.8, 'rest': 125.56, 'charge': '-'},
            {'date': '10-07', 'temp': 29.5, 'cost': 4.4, 'rest': 130.04, 'charge': '-'},
            {'date': '10-06', 'temp': 28.0, 'cost': 25.8, 'rest': 155.87, 'charge': 285.8},
            {'date': '10-05', 'temp': 27.0, 'cost': 18.6, 'rest': 174.52, 'charge': '-'},
            {'date': '10-04', 'temp': 26.0, 'cost': 22.0, 'rest': 196.57, 'charge': '-'},
        ]

    def test_table_and_chart_sections_unchanged(self):
        msg = sc_sender.handle(self.data, '测试宿舍101电量查询',
                               analysis_text='**用电规律分析**\n')
        desp = msg['desp']
        self.assertTrue(desp.startswith('测试宿舍101电量查询\n\n'))
        self.assertIn('**剩余电量趋势**\n\n![剩余电量](https://quickchart.io/chart?c=', desp)
        self.assertIn('**每日用电量与气温**\n\n![用电量与气温](https://quickchart.io/chart?c=', desp)
        self.assertIn('**用电规律分析**', desp)
        self.assertIn('| 日期 | 温度 | 用电 | 剩余 | 充电 |', desp)
        self.assertIn('| :---: | :---: | :---: | :---: | :---: |', desp)
        self.assertIn('| 10-08 | 30.00 | 5.80 | 125.56 | - |', desp)
        self.assertIn('| 10-06 | 28.00 | 25.80 | 155.87 | 285.80 |', desp)
        self.assertIn('预计还有', msg['text'])

    def test_low_power_threshold_message(self):
        msg = sc_sender.handle(self.data, 'X', low_power_threshold=200)
        self.assertIn('低于', msg['text'])
        self.assertIn('电量偏低，请尽快充值。', msg['desp'])


if __name__ == '__main__':
    unittest.main()
