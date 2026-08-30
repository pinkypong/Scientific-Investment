"""Retry / timeout / backoff (스펙 §13). 일정 횟수 초과 실패하면 중단."""
from __future__ import annotations

import functools
import time
from typing import Callable, Iterable, Type


class SourceUnavailable(RuntimeError):
    """일정 재시도 후에도 실패 — 호출측은 조용히 다른 소스로 대체 금지(스펙 §14)."""


def _no_retry_types():
    """재시도가 무의미한 예외들. 순환 import 를 피해 지연 로딩한다."""
    from .netguard import NoNetworkError
    return (NoNetworkError,)


NO_RETRY = _no_retry_types()


def retry_with_backoff(
    fn: Callable | None = None,
    *,
    retries: int = 3,
    base_delay: float = 1.0,
    factor: float = 2.0,
    exceptions: Iterable[Type[BaseException]] = (Exception,),
    on_retry: Callable[[int, BaseException], None] | None = None,
):
    """데코레이터 겸 직접호출. delay: base, base*factor, base*factor^2 ..."""

    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            delay = base_delay
            last: BaseException | None = None
            for attempt in range(1, retries + 1):
                try:
                    return f(*args, **kwargs)
                except NO_RETRY:
                    # Phase D §3: no-network 차단은 일시적 장애가 아니다.
                    # 재시도해도 결과가 같고, 백오프만큼 헛되이 기다리게 된다 → 그대로 올린다.
                    raise
                except tuple(exceptions) as e:  # noqa: B014
                    last = e
                    if on_retry:
                        on_retry(attempt, e)
                    if attempt == retries:
                        break
                    time.sleep(delay)
                    delay *= factor
            raise SourceUnavailable(
                f"{getattr(f, '__name__', 'call')} 실패 ({retries}회): {last!r}"
            ) from last

        return wrapper

    return deco(fn) if callable(fn) else deco


class RateLimiter:
    """요청 간 최소 간격 (스펙 §20 최소 요청)."""

    def __init__(self, delay_sec: float = 1.5) -> None:
        self.delay = max(0.0, float(delay_sec))
        self._last = 0.0

    def wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()
