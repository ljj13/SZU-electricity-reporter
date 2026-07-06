import csv
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import data_store
import main
import charts
import crawler
import sc_sender
import web_report


class DataStoreSaveTests(unittest.TestCase):
    def test_save_updates_existing_date_when_new_values_are_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "electricity_history.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=data_store.FIELDS)
                writer.writeheader()
                writer.writerow({
                    "date": "07-05",
                    "cost": "-",
                    "rest": "86.74",
                    "charge": "-",
                    "temp": "32.0",
                })

            rows = [{
                "date": "07-05",
                "cost": 23.75,
                "rest": 86.74,
                "charge": "-",
                "temp": 32.0,
            }]

            with mock.patch.object(data_store, "CSV_FILE", csv_path):
                data_store.save(rows)

            with open(csv_path, encoding="utf-8") as f:
                saved = list(csv.DictReader(f))

            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["date"], "2026-07-05")
            self.assertEqual(saved[0]["cost"], "23.75")
            self.assertEqual(saved[0]["rest"], "86.74")
            self.assertEqual(saved[0]["charge"], "-")
            self.assertEqual(saved[0]["temp"], "32.0")

    def test_save_merges_full_date_with_legacy_mm_dd_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "electricity_history.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=data_store.FIELDS)
                writer.writeheader()
                writer.writerow({
                    "date": "07-05",
                    "cost": "-",
                    "rest": "86.74",
                    "charge": "-",
                    "temp": "",
                })

            rows = [{
                "date": "2026-07-05",
                "cost": 23.75,
                "rest": 86.74,
                "charge": "-",
                "temp": 32.0,
            }]

            with mock.patch.object(data_store, "CSV_FILE", csv_path):
                data_store.save(rows)

            with open(csv_path, encoding="utf-8") as f:
                saved = list(csv.DictReader(f))

            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["date"], "2026-07-05")
            self.assertEqual(saved[0]["cost"], "23.75")
            self.assertEqual(saved[0]["temp"], "32.0")


class CrawlerParserTests(unittest.TestCase):
    def test_parse_html_table_data_without_regex(self):
        html = """
        <table>
          <tr>
            <td width="22%" align="center">2026-07-05 00:00</td>
            <td width="13%" align="center">0</td>
            <td width="13%" align="center">999.00</td>
            <td width="13%" align="center">86.74</td>
            <td width="13%" align="center">300.00</td>
            <td width="13%" align="center">400.00</td>
          </tr>
        </table>
        """

        self.assertEqual(crawler.parse_table_data(html), [["2026-07-05", 86.74, 300.0, 400.0]])


class SenderHandleTests(unittest.TestCase):
    def test_handle_uses_first_row_as_latest_data(self):
        today = time.strftime("%m-%d", time.localtime())
        data = [
            {"date": today, "cost": "-", "rest": 42.5, "charge": "-", "temp": 32.0},
            {"date": "07-05", "cost": 3.25, "rest": 45.75, "charge": "-", "temp": 31.0},
            {"date": "07-04", "cost": 4.0, "rest": 49.0, "charge": "-", "temp": 30.0},
        ]

        message = sc_sender.handle(data, "测试宿舍电量查询")

        self.assertEqual(message["text"], "预计还有 13 天需要充值电费")

    def test_handle_uses_prediction_as_title_when_data_is_not_updated_today(self):
        data = [
            {"date": "07-05", "cost": "-", "rest": 42.5, "charge": "-", "temp": 32.0},
            {"date": "07-04", "cost": 3.25, "rest": 45.75, "charge": "-", "temp": 31.0},
        ]

        message = sc_sender.handle(data, "测试宿舍电量查询")

        self.assertEqual(message["text"], "预计还有 13 天需要充值电费")

    def test_handle_uses_urgent_title_when_prediction_reaches_zero(self):
        data = [
            {"date": "07-06", "cost": "-", "rest": 0.2, "charge": "-", "temp": 32.0},
            {"date": "07-05", "cost": 3.25, "rest": 3.45, "charge": "-", "temp": 31.0},
        ]

        message = sc_sender.handle(data, "测试宿舍电量查询")

        self.assertEqual(message["text"], "电量即将耗尽，请尽快充值")

    def test_handle_uses_low_power_threshold_title(self):
        data = [
            {"date": "07-06", "cost": "-", "rest": 18.5, "charge": "-", "temp": 32.0},
            {"date": "07-05", "cost": 3.25, "rest": 21.75, "charge": "-", "temp": 31.0},
        ]

        message = sc_sender.handle(data, "测试宿舍电量查询", low_power_threshold=20)

        self.assertEqual(message["text"], "剩余电量 18.50 度，低于 20 度阈值")


class SenderSendTests(unittest.TestCase):
    def test_send_returns_true_when_server_chan_succeeds(self):
        response = mock.Mock()
        response.json.return_value = {"code": 0, "message": ""}
        with mock.patch("sc_sender._request_with_retry", return_value=response):
            self.assertTrue(sc_sender.send("SCT_TEST_SENDKEY", {"text": "title", "desp": "body"}))

    def test_send_returns_false_when_server_chan_rejects(self):
        response = mock.Mock()
        response.json.return_value = {"code": 40001, "message": "bad key"}
        with mock.patch("sc_sender._request_with_retry", return_value=response):
            self.assertFalse(sc_sender.send("SCT_TEST_SENDKEY", {"text": "title", "desp": "body"}))


class WebReportTests(unittest.TestCase):
    def test_write_report_creates_html_file_with_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.html"
            data = [
                {"date": "07-06", "cost": "-", "rest": 42.5, "charge": "-", "temp": 32.0},
                {"date": "07-05", "cost": 3.25, "rest": 45.75, "charge": "-", "temp": 31.0},
            ]

            path = web_report.write_report(
                data,
                "示例宿舍电量查询",
                "**用电规律分析**\n- 最近 2 天平均用电 3.2 度/天",
                output_path=output_path,
            )

            html = path.read_text(encoding="utf-8")
            self.assertIn("示例宿舍电量查询", html)
            self.assertIn("42.50 度", html)


class ChartTests(unittest.TestCase):
    def test_rest_chart_has_extra_top_padding(self):
        data = [
            {"date": "07-05", "cost": "-", "rest": 86.74, "charge": "-", "temp": 32.0},
            {"date": "07-04", "cost": 23.75, "rest": 110.49, "charge": "-", "temp": 29.1},
            {"date": "07-03", "cost": 22.83, "rest": 133.32, "charge": "-", "temp": 32.0},
            {"date": "07-02", "cost": 20.54, "rest": 153.86, "charge": "-", "temp": 32.5},
            {"date": "07-01", "cost": 27.79, "rest": 181.65, "charge": "-", "temp": 32.7},
        ]

        chart_url = charts.build_rest_chart_url(data)

        self.assertIn("%22layout%22", chart_url)
        self.assertIn("%22padding%22", chart_url)
        self.assertIn("%22top%22%3A%2024", chart_url)


class DailyRunGuardTests(unittest.TestCase):
    def test_run_once_per_day_skips_after_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "last_success.txt"
            today = "2026-07-06"
            calls = []

            def fake_job():
                calls.append("ran")
                return True

            self.assertTrue(main.run_once_per_day(fake_job, today=today, state_path=state_path))
            self.assertFalse(main.run_once_per_day(fake_job, today=today, state_path=state_path))
            self.assertEqual(calls, ["ran"])
            self.assertEqual(state_path.read_text(encoding="utf-8"), today)

    def test_run_once_per_day_retries_after_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "last_success.txt"
            today = "2026-07-06"
            calls = []

            def fake_job():
                calls.append("ran")
                return False

            self.assertFalse(main.run_once_per_day(fake_job, today=today, state_path=state_path))
            self.assertFalse(state_path.exists())
            self.assertFalse(main.run_once_per_day(fake_job, today=today, state_path=state_path))
            self.assertEqual(calls, ["ran", "ran"])


class ConfigTests(unittest.TestCase):
    def test_get_config_merges_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(
                '{"room_name": "ROOM", "room_id": "BUILDING", "client": "CLIENT"}',
                encoding="utf-8",
            )
            with mock.patch("main._get_config_path", return_value=config_path):
                config = main.getConfig()

            self.assertEqual(config["interval_day"], 14)
            self.assertFalse(config["dry_run"])
            self.assertEqual(config["low_power_threshold"], 20)


