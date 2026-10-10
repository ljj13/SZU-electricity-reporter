"""net_egress 单元测试：出口解析、Session 隔离、有界重试与回退顺序。"""

import os
import unittest
from unittest import mock

import requests

import net_egress


def make_response(status=200, payload=None):
    resp = mock.MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else {}
    resp.text = ''
    if status >= 400:
        error = requests.exceptions.HTTPError('HTTP %s' % status, response=resp)
        resp.raise_for_status.side_effect = error
    else:
        resp.raise_for_status.return_value = None
    return resp


class ParseSpecTests(unittest.TestCase):
    def test_order_is_preserved(self):
        self.assertEqual(net_egress.parse_spec('proxy,fallback,direct'),
                         ['proxy', 'fallback', 'direct'])

    def test_duplicates_are_removed(self):
        self.assertEqual(net_egress.parse_spec('proxy,proxy,direct'), ['proxy', 'direct'])

    def test_unknown_token_is_ignored(self):
        self.assertEqual(net_egress.parse_spec('proxy,warp,direct'), ['proxy', 'direct'])

    def test_empty_falls_back_to_default(self):
        self.assertEqual(net_egress.parse_spec('   '), ['proxy', 'fallback', 'direct'])

    def test_list_input_supported(self):
        self.assertEqual(net_egress.parse_spec(['direct', 'proxy']), ['direct', 'proxy'])


class SessionTests(unittest.TestCase):
    def test_direct_session_has_no_proxies(self):
        session = net_egress.build_session(net_egress.EGRESS_DIRECT)
        self.assertEqual(session.proxies, {})
        self.assertFalse(session.trust_env)

    def test_direct_session_ignores_environment_proxy(self):
        env = {'HTTP_PROXY': 'http://127.0.0.1:9', 'HTTPS_PROXY': 'http://127.0.0.1:9'}
        with mock.patch.dict(os.environ, env):
            session = net_egress.build_session(net_egress.EGRESS_DIRECT)
        self.assertEqual(session.proxies, {})
        self.assertFalse(session.trust_env)

    def test_proxy_session_sets_both_schemes(self):
        session = net_egress.build_session(net_egress.EGRESS_PROXY,
                                           proxy_url='http://127.0.0.1:7899')
        self.assertEqual(session.proxies,
                         {'http': 'http://127.0.0.1:7899', 'https': 'http://127.0.0.1:7899'})
        self.assertFalse(session.trust_env)

    def test_fallback_session_without_url_is_direct(self):
        session = net_egress.build_session(net_egress.EGRESS_FALLBACK, fallback_proxy_url='')
        self.assertEqual(session.proxies, {})

    def test_building_sessions_does_not_touch_process_environment(self):
        before = dict(os.environ)
        for token in (net_egress.EGRESS_DIRECT, net_egress.EGRESS_PROXY,
                      net_egress.EGRESS_FALLBACK):
            net_egress.build_session(token, 'http://127.0.0.1:7899', 'http://127.0.0.1:7890')
        self.assertEqual(before, dict(os.environ))


class RequestTests(unittest.TestCase):
    def _patch_session(self, behaviour):
        """behaviour: dict egress -> list of results (Exception 实例或 response)。"""
        sessions = {}

        def fake_build(egress, proxy_url=None, fallback_proxy_url=None):
            session = mock.MagicMock()
            session.proxies = {'http': str(egress), 'https': str(egress)}
            session._egress = egress
            outcomes = behaviour.get(egress, [])
            session.request.side_effect = outcomes if outcomes else [
                requests.exceptions.ConnectionError('no more outcomes')]
            sessions[egress] = session
            return session

        return fake_build, sessions

    def test_returns_response_and_used_egress(self):
        builder, sessions = self._patch_session({
            net_egress.EGRESS_PROXY: [make_response(200)],
        })
        with mock.patch.object(net_egress, 'build_session', side_effect=builder):
            resp, used = net_egress.request('POST', 'https://example.test/x',
                                            egress='proxy,direct', retries=1,
                                            read_timeout=1, connect_timeout=1)
        self.assertEqual(used, 'proxy')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(sessions.keys()), ['proxy'])

    def test_chain_order_proxy_then_fallback_then_direct(self):
        builder, sessions = self._patch_session({
            net_egress.EGRESS_PROXY: [requests.exceptions.ConnectionError('proxy down')],
            net_egress.EGRESS_FALLBACK: [requests.exceptions.ConnectionError('fallback down')],
            net_egress.EGRESS_DIRECT: [make_response(200)],
        })
        with mock.patch.object(net_egress, 'build_session', side_effect=builder):
            resp, used = net_egress.request('GET', 'https://example.test/x',
                                            egress='proxy,fallback,direct', retries=1,
                                            backoff=[0], read_timeout=1, connect_timeout=1)
        self.assertEqual(used, 'direct')

    def test_attempts_are_bounded(self):
        builder, sessions = self._patch_session({
            net_egress.EGRESS_PROXY: [requests.exceptions.ConnectTimeout('t'),
                                      requests.exceptions.ConnectTimeout('t')],
            net_egress.EGRESS_DIRECT: [requests.exceptions.ConnectTimeout('t'),
                                       requests.exceptions.ConnectTimeout('t')],
        })
        with mock.patch.object(net_egress, 'build_session', side_effect=builder):
            with self.assertRaises(requests.exceptions.ConnectTimeout):
                net_egress.request('POST', 'https://example.test/x',
                                   egress='proxy,direct', retries=2, backoff=[0],
                                   read_timeout=1, connect_timeout=1)
        self.assertEqual(sessions['proxy'].request.call_count, 2)
        self.assertEqual(sessions['direct'].request.call_count, 2)

    def test_permanent_4xx_is_not_retried_or_switched(self):
        builder, sessions = self._patch_session({
            net_egress.EGRESS_PROXY: [make_response(400)],
            net_egress.EGRESS_DIRECT: [make_response(200)],
        })
        with mock.patch.object(net_egress, 'build_session', side_effect=builder):
            with self.assertRaises(requests.exceptions.HTTPError):
                net_egress.request('POST', 'https://example.test/x',
                                   egress='proxy,direct', retries=2, backoff=[0],
                                   read_timeout=1, connect_timeout=1)
        self.assertEqual(sessions['proxy'].request.call_count, 1)
        self.assertNotIn('direct', sessions)

    def test_rate_limit_429_is_retried(self):
        builder, sessions = self._patch_session({
            net_egress.EGRESS_PROXY: [make_response(429), make_response(200)],
        })
        with mock.patch.object(net_egress, 'build_session', side_effect=builder):
            resp, used = net_egress.request('POST', 'https://example.test/x',
                                            egress='proxy', retries=2, backoff=[0],
                                            read_timeout=1, connect_timeout=1)
        self.assertEqual(used, 'proxy')
        self.assertEqual(sessions['proxy'].request.call_count, 2)

    def test_post_read_timeout_stops_retries_and_egress_switching(self):
        # POST 等待响应超时可能远端已处理，为避免重复推送必须立刻停止重试与换出口
        builder, sessions = self._patch_session({
            net_egress.EGRESS_PROXY: [requests.exceptions.ReadTimeout('slow read')],
            net_egress.EGRESS_DIRECT: [make_response(200)],
        })
        with mock.patch.object(net_egress, 'build_session', side_effect=builder):
            with self.assertRaises(requests.exceptions.ReadTimeout):
                net_egress.request('POST', 'https://example.test/push',
                                   egress='proxy,direct', retries=3, backoff=[0],
                                   read_timeout=1, connect_timeout=1)
        self.assertEqual(sessions['proxy'].request.call_count, 1)
        self.assertNotIn('direct', sessions)

    def test_post_read_timeout_retries_when_explicitly_enabled(self):
        # 允许幂等 POST 查询（如内网电量查询）显式开启重试
        builder, sessions = self._patch_session({
            net_egress.EGRESS_PROXY: [requests.exceptions.ReadTimeout('slow read'),
                                      make_response(200)],
        })
        with mock.patch.object(net_egress, 'build_session', side_effect=builder):
            resp, used = net_egress.request('POST', 'https://example.test/query',
                                            egress='proxy', retries=2, backoff=[0],
                                            retry_post_read_timeout=True,
                                            read_timeout=1, connect_timeout=1)
        self.assertEqual(used, 'proxy')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(sessions['proxy'].request.call_count, 2)

    def test_get_read_timeout_is_retried_normally(self):
        # GET 是幂等操作，ReadTimeout 正常重试
        builder, sessions = self._patch_session({
            net_egress.EGRESS_PROXY: [requests.exceptions.ReadTimeout('slow read'),
                                      make_response(200)],
        })
        with mock.patch.object(net_egress, 'build_session', side_effect=builder):
            resp, used = net_egress.request('GET', 'https://example.test/weather',
                                            egress='proxy', retries=2, backoff=[0],
                                            read_timeout=1, connect_timeout=1)
        self.assertEqual(used, 'proxy')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(sessions['proxy'].request.call_count, 2)

    def test_skips_unconfigured_fallback(self):
        builder, sessions = self._patch_session({
            net_egress.EGRESS_PROXY: [requests.exceptions.ConnectionError('x')],
            net_egress.EGRESS_DIRECT: [make_response(200)],
        })
        with mock.patch.object(net_egress, 'build_session', side_effect=builder):
            _, used = net_egress.request('GET', 'https://example.test/x',
                                         egress='proxy,fallback,direct', retries=1,
                                         backoff=[0], proxy_url='http://127.0.0.1:7899',
                                         fallback_proxy_url='',
                                         read_timeout=1, connect_timeout=1)
        self.assertEqual(used, 'direct')
        self.assertNotIn('fallback', sessions)

    def test_describe_lists_urls(self):
        text = net_egress.describe('proxy,fallback,direct', 'http://127.0.0.1:7899',
                                   'http://127.0.0.1:7890')
        self.assertIn('http://127.0.0.1:7899', text)
        self.assertIn('http://127.0.0.1:7890', text)
        self.assertTrue(text.endswith('direct'))

    def test_short_error_is_one_line(self):
        exc = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='x', port=443): Max retries exceeded "
            "(Caused by NewConnectionError('... Connection refused'))")
        text = net_egress.short_error(exc)
        self.assertNotIn('\n', text)
        self.assertIn('Connection refused', text)

    def test_short_error_compresses_proxy_error(self):
        exc = requests.exceptions.ProxyError(
            "HTTPSConnectionPool(host='sctapi.ftqq.com', port=443): Max retries exceeded "
            "(Caused by ProxyError('Unable to connect to proxy', "
            "NewConnectionError(\"HTTPSConnection(host='127.0.0.1', port=1): "
            "Failed to establish a new connection: [Errno 111] Connection refused\")))")
        text = net_egress.short_error(exc)
        self.assertEqual(text, 'ProxyError: Connection refused（本机代理未监听？）')
        self.assertLess(len(text), 60)

    def test_short_error_http_status(self):
        resp = mock.MagicMock()
        resp.status_code = 502
        exc = requests.exceptions.HTTPError('bad gateway', response=resp)
        self.assertEqual(net_egress.short_error(exc), 'HTTP 502')


if __name__ == '__main__':
    unittest.main()
