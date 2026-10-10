"""每日去重状态机：失败不占用当天、dry-run 不占用当天、成功才写状态。"""

import json
import tempfile
import unittest
from pathlib import Path

import main


class RunOncePerDayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='szu-state-'))
        self.state = self.tmp / 'last_success_date.txt'

    def test_failure_does_not_write_state(self):
        status = main.run_once_per_day(lambda: False, today='2026-10-09',
                                       state_path=self.state)
        self.assertEqual(status, 'failed')
        self.assertFalse(self.state.exists())

    def test_success_writes_state_with_details(self):
        status = main.run_once_per_day(
            lambda: {'ok': True, 'title': '预计还有 7 天', 'location': '测试宿舍101'},
            today='2026-10-09', state_path=self.state)
        self.assertEqual(status, 'success')
        state = json.loads(self.state.read_text(encoding='utf-8'))
        self.assertEqual(state['date'], '2026-10-09')
        self.assertTrue(state['ok'])
        self.assertEqual(state['title'], '预计还有 7 天')
        self.assertIn('sent_at', state)

    def test_second_trigger_same_day_is_skipped(self):
        calls = []

        def task():
            calls.append(1)
            return True

        main.run_once_per_day(task, today='2026-10-09', state_path=self.state)
        status = main.run_once_per_day(task, today='2026-10-09', state_path=self.state)
        self.assertEqual(status, 'skipped')
        self.assertEqual(len(calls), 1)

    def test_force_bypasses_skip(self):
        calls = []

        def task():
            calls.append(1)
            return True

        main.run_once_per_day(task, today='2026-10-09', state_path=self.state)
        main.run_once_per_day(task, today='2026-10-09', state_path=self.state, force=True)
        self.assertEqual(len(calls), 2)

    def test_dry_run_result_does_not_consume_day(self):
        calls = []

        def dry_run_task():
            calls.append(1)
            return {'ok': True, 'update_state': False, 'title': 'dry_run'}

        status = main.run_once_per_day(dry_run_task, today='2026-10-09',
                                       state_path=self.state)
        self.assertEqual(status, 'success')
        self.assertFalse(self.state.exists())
        main.run_once_per_day(
            lambda: {'ok': True, 'title': '正式推送'}, today='2026-10-09',
            state_path=self.state)
        self.assertEqual(json.loads(self.state.read_text(encoding='utf-8'))['title'],
                         '正式推送')

    def test_missing_key_result_does_not_consume_day(self):
        def missing_key_task():
            return {'ok': True, 'update_state': False, 'title': '未配置 server_chan_key，未发送微信'}

        status = main.run_once_per_day(missing_key_task, today='2026-10-09',
                                       state_path=self.state)
        self.assertEqual(status, 'success')
        self.assertFalse(self.state.exists())

    def test_task_exception_is_contained(self):
        def boom():
            raise RuntimeError('boom')

        status = main.run_once_per_day(boom, today='2026-10-09', state_path=self.state)
        self.assertEqual(status, 'failed')
        self.assertFalse(self.state.exists())

    def test_previous_day_state_allows_new_run(self):
        main.run_once_per_day(lambda: True, today='2026-10-08', state_path=self.state)
        status = main.run_once_per_day(lambda: True, today='2026-10-09',
                                       state_path=self.state)
        self.assertEqual(status, 'success')

    def test_corrupt_state_file_is_self_healing(self):
        self.state.write_text('{not json', encoding='utf-8')
        status = main.run_once_per_day(lambda: True, today='2026-10-09',
                                       state_path=self.state)
        self.assertEqual(status, 'success')
        self.assertEqual(json.loads(self.state.read_text(encoding='utf-8'))['date'],
                         '2026-10-09')

    def test_legacy_plain_date_state_is_supported(self):
        self.state.write_text('2026-10-09', encoding='utf-8')
        status = main.run_once_per_day(lambda: True, today='2026-10-09',
                                       state_path=self.state)
        self.assertEqual(status, 'skipped')

    def test_state_write_is_atomic(self):
        main.run_once_per_day(lambda: True, today='2026-10-09', state_path=self.state)
        leftovers = list(self.tmp.glob('*.tmp'))
        self.assertEqual(leftovers, [])

    def test_state_file_is_parseable_after_write(self):
        main.run_once_per_day(lambda: {'ok': True}, today='2026-10-09',
                              state_path=self.state)
        json.loads(self.state.read_text(encoding='utf-8'))

    def test_already_done_today_helper(self):
        self.assertFalse(main.already_done_today('2026-10-09', self.state))
        main.run_once_per_day(lambda: True, today='2026-10-09', state_path=self.state)
        self.assertTrue(main.already_done_today('2026-10-09', self.state))
        self.assertFalse(main.already_done_today('2026-10-10', self.state))


if __name__ == '__main__':
    unittest.main()
