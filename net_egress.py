"""网络出口策略（最小依赖，集中管理本项目的全部出网路径）。

设计约束（与部署环境一致）：
1. 校园内网（电量查询 ``http://192.168.84.3:9090/``）**永远直连**，且不受环境变量、
   系统代理或本模块配置影响。
2. Server酱（``sctapi.ftqq.com``，国内域名）在本板所在的校园网直连被拒，必须经本机
   代理出口访问（默认 ``http://127.0.0.1:7899``，专用出口实例）。
3. 天气（``api.open-meteo.com``）优先代理，失败后允许直连回退。
4. 本模块**不读写** ``os.environ``、不设置系统/全局代理，只对显式构造的 Session 生效
   （``trust_env=False``），因此不会影响板上的其他服务。
5. 所有请求都有显式超时与有界重试，任何失败都会以简短原因写日志，不产生巨型堆栈。
"""

from __future__ import annotations

import logging
import time
from typing import Iterable, List, Optional, Sequence, Tuple

import requests

logger = logging.getLogger('electricity')

# ── 出口类型 ──────────────────────────────────────────────
EGRESS_DIRECT = 'direct'
EGRESS_PROXY = 'proxy'
EGRESS_FALLBACK = 'fallback'

VALID_EGRESS = (EGRESS_DIRECT, EGRESS_PROXY, EGRESS_FALLBACK)

# ── 默认值（可在 config.json 中覆盖）──────────────────────
DEFAULT_PROXY_URL = 'http://127.0.0.1:7899'
DEFAULT_FALLBACK_PROXY_URL = 'http://127.0.0.1:7890'
DEFAULT_SPEC = 'proxy,fallback,direct'
DEFAULT_CONNECT_TIMEOUT = 4.0
DEFAULT_READ_TIMEOUT = 20.0
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = (2.0,)

# 这些 4xx 属于可重试/可换出口（限流、超时语义），其余 4xx 视为永久错误
RETRYABLE_HTTP = frozenset({408, 425, 429})


def parse_spec(spec, default: str = DEFAULT_SPEC) -> List[str]:
    """把 ``"proxy,fallback,direct"`` 解析为有序去重的出口列表。

    非法或空配置回退到 ``default``；未知出口类型被忽略并告警。
    """
    if isinstance(spec, (list, tuple)):
        raw: Sequence[str] = [str(item) for item in spec]
    elif isinstance(spec, str):
        raw = spec.split(',')
    else:
        raw = []

    chain: List[str] = []
    for item in raw:
        token = item.strip().lower()
        if not token:
            continue
        if token not in VALID_EGRESS:
            logger.warning('忽略未知出口类型 %r（可选：%s）', item, '/'.join(VALID_EGRESS))
            continue
        if token not in chain:
            chain.append(token)

    if not chain:
        chain = [token.strip().lower() for token in str(default).split(',') if token.strip()]
    return chain


def proxy_urls(proxy_url: Optional[str], fallback_proxy_url: Optional[str]) -> dict:
    return {
        EGRESS_PROXY: (proxy_url or DEFAULT_PROXY_URL).strip(),
        EGRESS_FALLBACK: (fallback_proxy_url or '').strip(),
    }


def build_session(egress: str, proxy_url: Optional[str] = None,
                  fallback_proxy_url: Optional[str] = None) -> requests.Session:
    """构造一个显式出口的 Session。

    ``trust_env=False`` 保证环境变量/系统代理不会泄漏进来；直连出口显式清空 proxies。
    """
    session = requests.Session()
    session.trust_env = False

    if egress == EGRESS_PROXY:
        url = (proxy_url or DEFAULT_PROXY_URL).strip()
        session.proxies = {'http': url, 'https': url}
    elif egress == EGRESS_FALLBACK:
        url = (fallback_proxy_url or '').strip()
        if url:
            session.proxies = {'http': url, 'https': url}
    # direct：显式无代理
    return session


def short_error(exc: BaseException) -> str:
    """把 requests 的嵌套异常压缩成一行可读原因。"""
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return 'HTTP %s' % exc.response.status_code
    if isinstance(exc, requests.exceptions.ProxyError):
        text = str(exc).lower()
        if 'connection refused' in text:
            return 'ProxyError: Connection refused（本机代理未监听？）'
        if 'timed out' in text or 'timeout' in text:
            return 'ProxyError: Timeout（本机代理无响应）'
        if 'unable to connect' in text:
            return 'ProxyError: Unable to connect'
        return 'ProxyError'
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return 'ConnectTimeout'
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return 'ReadTimeout'
    if isinstance(exc, requests.exceptions.ConnectionError):
        text = str(exc)
        for marker in ('Connection refused', 'Name or service not known',
                       'Temporary failure in name resolution', 'unexpected eof',
                       'Remote end closed'):
            if marker in text:
                return 'ConnectionError: %s' % marker
        return 'ConnectionError'
    return '%s: %s' % (type(exc).__name__, exc)


def describe(spec, proxy_url: Optional[str] = None,
             fallback_proxy_url: Optional[str] = None) -> str:
    """用于启动日志的出口描述。"""
    urls = proxy_urls(proxy_url, fallback_proxy_url)
    parts = []
    for token in parse_spec(spec):
        if token == EGRESS_DIRECT:
            parts.append('direct')
        else:
            parts.append('%s(%s)' % (token, urls.get(token) or '未配置'))
    return ' -> '.join(parts) if parts else 'direct'


def request(method: str, url: str, *, egress, proxy_url: Optional[str] = None,
            fallback_proxy_url: Optional[str] = None,
            retries: int = DEFAULT_RETRIES,
            backoff: Iterable[float] = DEFAULT_BACKOFF,
            connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
            read_timeout: float = DEFAULT_READ_TIMEOUT,
            timeout: Optional[Tuple[float, float]] = None,
            retry_post_read_timeout: bool = False,
            **kwargs) -> Tuple[requests.Response, str]:
    """按出口链顺序请求，返回 ``(response, 实际使用的出口)``。

    每个出口最多尝试 ``retries`` 次、按 ``backoff`` 退避；全部失败时抛出最后一次异常。
    针对非幂等的 POST 请求，当发生 ReadTimeout 时默认不重试/不切换出口，避免重复推送风险。
    """
    chain = parse_spec(egress)
    urls = proxy_urls(proxy_url, fallback_proxy_url)
    attempts = max(1, int(retries))
    waits = list(backoff) or [0]
    request_timeout = timeout or (connect_timeout, read_timeout)
    is_post = str(method).strip().upper() == 'POST'

    last_exc: Optional[BaseException] = None
    for token in chain:
        if token == EGRESS_FALLBACK and not urls[EGRESS_FALLBACK]:
            continue
        if token == EGRESS_PROXY and not urls[EGRESS_PROXY]:
            continue

        session = build_session(token, urls[EGRESS_PROXY], urls[EGRESS_FALLBACK])
        try:
            for attempt in range(1, attempts + 1):
                try:
                    logger.debug('HTTP %s %s (出口=%s, 第%d次)', method, url, token, attempt)
                    resp = session.request(method, url, timeout=request_timeout, **kwargs)
                    resp.raise_for_status()
                    return resp, token
                except requests.exceptions.HTTPError as exc:
                    # 除 408/429 外，4xx 属于永久性错误（例如 SendKey 无效），
                    # 换出口或重试没有意义，直接抛出交给调用方解释响应体。
                    status = exc.response.status_code if exc.response is not None else None
                    if status is not None and 400 <= status < 500 and status not in RETRYABLE_HTTP:
                        raise
                    last_exc = exc
                    logger.warning('请求失败 (出口=%s, 第%d次): %s', token, attempt,
                                   short_error(exc))
                except requests.RequestException as exc:
                    last_exc = exc
                    logger.warning('请求失败 (出口=%s, 第%d次): %s', token, attempt,
                                   short_error(exc))
                    if is_post and isinstance(exc, requests.exceptions.ReadTimeout) and not retry_post_read_timeout:
                        logger.warning('POST 请求在等待响应时超时 (%s)，为避免重复推送风险，停止重试与出口切换',
                                       short_error(exc))
                        raise
                if attempt < attempts:
                    wait = waits[min(attempt - 1, len(waits) - 1)]
                    if wait:
                        time.sleep(wait)
        finally:
            session.close()

    if last_exc is None:
        raise requests.exceptions.ConnectionError('没有可用的网络出口: %s' % describe(egress))
    raise last_exc
