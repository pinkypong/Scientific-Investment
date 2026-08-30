"""no-network 가드 (Phase D §3·§5).

`--dry-run` 과 `--no-network` 는 다른 축이다:

  --dry-run     : 외부 **저장** 없음.  raw/normalized/derived/sync_state/health/log 미기록.
                  네트워크는 여전히 나갈 수 있다(TTL 이 만료되고 --force 면 실제 API 호출).
  --no-network  : 외부 **호출** 없음.  provider-level TTL skip 또는 company-level cache hit 만
                  허용하고, cache miss 는 API 를 때리지 않고 blocked 로 보고한다.
  둘을 같이 주면 완전 무해 점검 모드 — 아무것도 읽으러 나가지 않고 아무것도 쓰지 않는다.

가드는 규약이 아니라 **강제**다. 어댑터의 HTTP 진입점이 `guard()` 를 호출하므로,
no-network 상태에서 실수로 호출 경로가 열려 있으면 `NoNetworkError` 로 즉시 실패한다.
테스트는 이 성질을 이용해 "cache hit 시 네트워크 호출 없음"을 증명한다.
"""
from __future__ import annotations

_NO_NETWORK = False


class NoNetworkError(RuntimeError):
    """--no-network 상태에서 외부 호출이 시도됨. 메시지에 URL 쿼리를 넣지 않는다."""


def set_no_network(value: bool) -> None:
    global _NO_NETWORK
    _NO_NETWORK = bool(value)


def is_no_network() -> bool:
    return _NO_NETWORK


def guard(what: str = "external request") -> None:
    """외부 호출 직전에 부른다. no-network 이면 예외.

    `what` 에는 endpoint 이름처럼 **쿼리 없는** 식별자만 넘긴다 (자격증명 유출 방지)."""
    if _NO_NETWORK:
        raise NoNetworkError(f"no-network mode: blocked {what}")
