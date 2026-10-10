"""GUI 配置合并与旧配置/网络出口参数兼容性测试。"""

import unittest
from pathlib import Path
import tempfile

import config_gui
import config_store


class ConfigGuiMergeTests(unittest.TestCase):
    def test_merge_preserves_custom_egress_parameters(self):
        base_config = {
            'room_name': '旧房间',
            'room_id': '8092',
            'client': '10.0.0.1',
            'proxy_url': 'http://127.0.0.1:1080',
            'proxy_fallback_url': 'http://127.0.0.1:1081',
            'server_chan_egress': 'direct,proxy',
            'weather_egress': 'direct',
            'push_retries': 4,
            'push_timeout': 45,
            'custom_user_key': 'keep_me',
        }
        gui_values = {
            'room_name': '新房间202',
            'room_id': '8092',
            'client': '10.0.0.2',
            'server_chan_key': 'SCT999999abcdef',
            'interval_day': 7,
            'remind_time': 10,
            'low_power_threshold': 15.0,
            'remind_daily': True,
            'dry_run': False,
        }
        merged = config_gui.merge_gui_config(base_config, gui_values, config_store.DEFAULT_CONFIG)

        # 界面修改的字段已更新
        self.assertEqual(merged['room_name'], '新房间202')
        self.assertEqual(merged['client'], '10.0.0.2')
        self.assertEqual(merged['server_chan_key'], 'SCT999999abcdef')
        self.assertEqual(merged['interval_day'], 7)
        self.assertEqual(merged['remind_time'], 10)
        self.assertEqual(merged['low_power_threshold'], 15.0)
        self.assertTrue(merged['remind_daily'])
        self.assertFalse(merged['dry_run'])

        # 界面未展示的自定义出口参数与额外字段必须完整保留，不得被默认值覆盖
        self.assertEqual(merged['proxy_url'], 'http://127.0.0.1:1080')
        self.assertEqual(merged['proxy_fallback_url'], 'http://127.0.0.1:1081')
        self.assertEqual(merged['server_chan_egress'], 'direct,proxy')
        self.assertEqual(merged['weather_egress'], 'direct')
        self.assertEqual(merged['push_retries'], 4)
        self.assertEqual(merged['push_timeout'], 45)
        self.assertEqual(merged['custom_user_key'], 'keep_me')

    def test_merge_uses_defaults_when_base_config_empty(self):
        gui_values = {
            'room_name': '101',
            'room_id': '8092',
            'client': '10.0.0.1',
            'server_chan_key': '',
            'interval_day': 14,
            'remind_time': 9,
            'low_power_threshold': 20.0,
            'remind_daily': False,
            'dry_run': False,
        }
        merged = config_gui.merge_gui_config({}, gui_values, config_store.DEFAULT_CONFIG)
        self.assertEqual(merged['proxy_url'], config_store.DEFAULT_CONFIG['proxy_url'])
        self.assertEqual(merged['server_chan_egress'], config_store.DEFAULT_CONFIG['server_chan_egress'])


if __name__ == '__main__':
    unittest.main()
