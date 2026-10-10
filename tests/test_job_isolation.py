"""job 异常隔离：天气/分析/CSV 故障不得阻断电费推送；推送失败不得写入成功状态。"""

import unittest
from unittest import mock

import requests

import main


def make_config(**overrides):
    config = {
        'room_name': '101',
        'room_id': '8092',
        'client': '10.0.0.1',
        'interval_day': 14,
        'remind_daily': True,
        'server_chan_key': 'SCT123456abcdef',
        'remind_time': 9,
        'city': '',
        'dry_run': False,
        'low_power_threshold': 20,
        'proxy_url': 'http://127.0.0.1:7899',
        'proxy_fallback_url': 'http://127.0.0.1:7890',
        'server_chan_egress': 'proxy,fallback,direct',
        'weather_egress': 'proxy,fallback,direct',
        'push_retries': 2,
        'push_timeout': 20,
    }
    config.update(overrides)
    return config


TABLE = [
    ['2026-10-08', 125.56, 100.0, 120.0],
    ['2026-10-07', 130.04, 95.0, 120.0],
    ['2026-10-06', 155.87, 70.0, 120.0],
]


class JobIsolationTests(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(main.buildings, 'get_building_name', return_value='测试楼'),
            mock.patch.object(main.crawler, 'crawlData', return_value=list(TABLE)),
            mock.patch.object(main.data_store, 'save'),
            mock.patch.object(main.data_store, 'update_temperatures'),
            mock.patch.object(main.analysis, 'analyze', return_value='分析'),
            mock.patch.object(main.sc_sender, 'handle',
                              return_value={'text': '标题', 'desp': '正文'}),
            mock.patch.object(main.sc_sender, 'send', return_value=True),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_weather_failure_does_not_block_push(self):
        with mock.patch.object(main.weather, 'fetch_temperature',
                               side_effect=RuntimeError('天气炸了')):
            result = main.job(make_config())
        self.assertTrue(result['ok'])
        main.sc_sender.send.assert_called_once()

    def test_weather_transport_failure_does_not_block_push(self):
        with mock.patch.object(main.weather, 'fetch_temperature',
                               side_effect=requests.exceptions.ConnectionError('down')):
            result = main.job(make_config())
        self.assertTrue(result['ok'])
        main.sc_sender.send.assert_called_once()

    def test_analysis_failure_does_not_block_push(self):
        main.analysis.analyze.side_effect = RuntimeError('分析炸了')
        with mock.patch.object(main.weather, 'fetch_temperature', return_value={}):
            result = main.job(make_config())
        self.assertTrue(result['ok'])
        main.sc_sender.send.assert_called_once()

    def test_csv_failure_does_not_block_push(self):
        main.data_store.save.side_effect = OSError('磁盘满')
        with mock.patch.object(main.weather, 'fetch_temperature', return_value={}):
            result = main.job(make_config())
        self.assertTrue(result['ok'])
        main.sc_sender.send.assert_called_once()

    def test_crawl_failure_returns_failed_and_skips_push(self):
        main.crawler.crawlData.side_effect = requests.exceptions.ConnectionError('内网不可达')
        result = main.job(make_config())
        self.assertFalse(result)
        main.sc_sender.send.assert_not_called()

    def test_empty_crawl_result_returns_failed(self):
        main.crawler.crawlData.return_value = []
        result = main.job(make_config())
        self.assertFalse(result)
        main.sc_sender.send.assert_not_called()

    def test_push_transport_failure_returns_failed_and_records_error(self):
        main.sc_sender.send.side_effect = requests.exceptions.ConnectionError('all down')
        with mock.patch.object(main, 'record_error') as recorded:
            with mock.patch.object(main.weather, 'fetch_temperature', return_value={}):
                result = main.job(make_config())
        self.assertFalse(result)
        recorded.assert_called_once()
        self.assertIn('所有出口', recorded.call_args[0][0])

    def test_push_api_failure_returns_failed(self):
        main.sc_sender.send.return_value = False
        with mock.patch.object(main, 'record_error') as recorded:
            with mock.patch.object(main.weather, 'fetch_temperature', return_value={}):
                result = main.job(make_config())
        self.assertFalse(result)
        recorded.assert_called_once()

    def test_push_receives_egress_configuration(self):
        with mock.patch.object(main.weather, 'fetch_temperature', return_value={}):
            main.job(make_config())
        kwargs = main.sc_sender.send.call_args.kwargs
        self.assertEqual(kwargs['egress'], 'proxy,fallback,direct')
        self.assertEqual(kwargs['proxy_url'], 'http://127.0.0.1:7899')
        self.assertEqual(kwargs['fallback_proxy_url'], 'http://127.0.0.1:7890')
        self.assertEqual(kwargs['retries'], 2)
        self.assertEqual(kwargs['timeout'], 20)

    def test_dry_run_does_not_push_and_does_not_consume_day(self):
        with mock.patch.object(main.weather, 'fetch_temperature', return_value={}):
            result = main.job(make_config(dry_run=True))
        self.assertTrue(result['ok'])
        self.assertFalse(result['update_state'])
        main.sc_sender.send.assert_not_called()

    def test_missing_server_chan_key_does_not_consume_day(self):
        with mock.patch.object(main.weather, 'fetch_temperature', return_value={}):
            result = main.job(make_config(server_chan_key=''))
        self.assertTrue(result['ok'])
        self.assertFalse(result.get('update_state'))
        main.sc_sender.send.assert_not_called()

    def test_missing_room_config_returns_failed(self):
        result = main.job(make_config(room_name=''))
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
