"""退出码与 --test-push 行为（受控测试推送不得污染当日日报状态）。"""

import unittest
from unittest import mock

import main
from tests.test_job_isolation import make_config


class ExitCodeTests(unittest.TestCase):
    def _run(self, argv, patches):
        """patches: {module_attribute: replacement_value}"""
        stack = []
        try:
            for target, replacement in patches.items():
                patcher = mock.patch.object(main, target, replacement)
                stack.append(patcher)
                patcher.start()
            return main.main(argv)
        finally:
            for patcher in reversed(stack):
                patcher.stop()

    def test_skipped_returns_zero(self):
        code = self._run(['--once', '--quiet'], {
            'getConfig': mock.Mock(return_value=make_config()),
            'validate_config': mock.Mock(return_value=[]),
            'run_once_per_day': mock.Mock(return_value='skipped'),
        })
        self.assertEqual(code, main.EXIT_OK)

    def test_success_returns_zero(self):
        code = self._run(['--once', '--quiet'], {
            'getConfig': mock.Mock(return_value=make_config()),
            'validate_config': mock.Mock(return_value=[]),
            'run_once_per_day': mock.Mock(return_value='success'),
        })
        self.assertEqual(code, main.EXIT_OK)

    def test_failed_returns_one(self):
        code = self._run(['--once', '--quiet'], {
            'getConfig': mock.Mock(return_value=make_config()),
            'validate_config': mock.Mock(return_value=[]),
            'run_once_per_day': mock.Mock(return_value='failed'),
        })
        self.assertEqual(code, main.EXIT_TASK_FAILED)

    def test_missing_config_returns_two(self):
        code = self._run(['--once', '--quiet'], {
            'getConfig': mock.Mock(side_effect=main.ConfigError('缺失')),
        })
        self.assertEqual(code, main.EXIT_CONFIG)

    def test_invalid_config_returns_two(self):
        code = self._run(['--once', '--quiet'], {
            'getConfig': mock.Mock(return_value=make_config()),
            'validate_config': mock.Mock(return_value=['room_name 不能为空']),
        })
        self.assertEqual(code, main.EXIT_CONFIG)


class TestPushTests(unittest.TestCase):
    def setUp(self):
        self.state_backup = None
        if main.RUN_STATE_FILE.exists():
            self.state_backup = main.RUN_STATE_FILE.read_text(encoding='utf-8')
            main.RUN_STATE_FILE.unlink()

    def test_successful_test_push_returns_zero_without_state(self):
        with mock.patch.object(main, 'getConfig', return_value=make_config()), \
             mock.patch.object(main, 'validate_config', return_value=[]), \
             mock.patch.object(main.buildings, 'get_building_name', return_value='测试楼'), \
             mock.patch.object(main.sc_sender, 'send', return_value=True) as sent:
            code = main.main(['--test-push', '--quiet'])
        self.assertEqual(code, main.EXIT_OK)
        self.assertTrue(sent.called)
        self.assertFalse(main.RUN_STATE_FILE.exists(),
                         '测试推送不得写入 last_success_date.txt')
        title = sent.call_args.kwargs['data']['text']
        self.assertIn('测试', title)
        self.assertNotIn('需要充值', title)

    def test_failed_test_push_returns_three(self):
        with mock.patch.object(main, 'getConfig', return_value=make_config()), \
             mock.patch.object(main, 'validate_config', return_value=[]), \
             mock.patch.object(main.sc_sender, 'send', return_value=False):
            code = main.main(['--test-push', '--quiet'])
        self.assertEqual(code, main.EXIT_PUSH_FAILED)
        self.assertFalse(main.RUN_STATE_FILE.exists())

    def test_test_push_without_key_returns_config_error(self):
        with mock.patch.object(main, 'getConfig',
                               return_value=make_config(server_chan_key='')), \
             mock.patch.object(main, 'validate_config', return_value=[]):
            code = main.main(['--test-push', '--quiet'])
        self.assertEqual(code, main.EXIT_CONFIG)

    def test_test_push_claims_not_daily_report(self):
        with mock.patch.object(main, 'getConfig', return_value=make_config()), \
             mock.patch.object(main, 'validate_config', return_value=[]), \
             mock.patch.object(main.buildings, 'get_building_name', return_value='测试楼'), \
             mock.patch.object(main.sc_sender, 'send', return_value=True) as sent:
            main.main(['--test-push', '--quiet'])
        desp = sent.call_args.kwargs['data']['desp']
        self.assertIn('不是当日电费日报', desp)
        self.assertIn('09:00', desp)


if __name__ == '__main__':
    unittest.main()
