"""weather：失败必须静默降级（不抛异常、不阻断推送），并复用出口链。"""

import unittest
from unittest import mock

import requests

import weather


class WeatherTests(unittest.TestCase):
    def test_parses_temperature_map(self):
        resp = mock.MagicMock()
        resp.json.return_value = {
            'daily': {
                'time': ['2026-10-07', '2026-10-08'],
                'temperature_2m_max': [29.4, 31.25],
            }
        }
        with mock.patch.object(weather.net_egress, 'request',
                               return_value=(resp, 'proxy')) as patched:
            result = weather.fetch_temperature(past_days=2, forecast_days=1,
                                               egress='proxy,direct')
        self.assertEqual(result, {'10-07': 29.4, '10-08': 31.2})
        kwargs = patched.call_args.kwargs
        self.assertEqual(kwargs['egress'], 'proxy,direct')
        self.assertEqual(kwargs['retries'], 1)

    def test_returns_empty_dict_on_transport_failure(self):
        with mock.patch.object(weather.net_egress, 'request',
                               side_effect=requests.exceptions.ConnectionError('down')):
            with self.assertLogs('electricity', level='WARNING') as captured:
                result = weather.fetch_temperature()
        self.assertEqual(result, {})
        self.assertTrue(any('气温获取失败' in line for line in captured.output))
        self.assertTrue(any('不影响电费推送' in line for line in captured.output))

    def test_returns_empty_dict_on_timeout(self):
        with mock.patch.object(weather.net_egress, 'request',
                               side_effect=requests.exceptions.ReadTimeout('slow')):
            self.assertEqual(weather.fetch_temperature(), {})

    def test_returns_empty_dict_on_bad_json(self):
        resp = mock.MagicMock()
        resp.json.side_effect = ValueError('bad json')
        with mock.patch.object(weather.net_egress, 'request', return_value=(resp, 'proxy')):
            self.assertEqual(weather.fetch_temperature(), {})

    def test_parameters_are_clamped(self):
        resp = mock.MagicMock()
        resp.json.return_value = {'daily': {'time': [], 'temperature_2m_max': []}}
        with mock.patch.object(weather.net_egress, 'request',
                               return_value=(resp, 'proxy')) as patched:
            weather.fetch_temperature(past_days=999, forecast_days=99)
        params = patched.call_args.kwargs['params']
        self.assertEqual(params['past_days'], 92)
        self.assertEqual(params['forecast_days'], 16)


if __name__ == '__main__':
    unittest.main()
