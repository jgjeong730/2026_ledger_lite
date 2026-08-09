"""카카오페이 송금(1/N 정산) 정규식 파서.

두 가지 실제 형식을 지원한다:

1) 방이름/방향/시각까지 포함된 형식:
    [모임방A] 6,800원을 보냈어요. (2026.08.06 19:58)
    [모임방A] 6,800원을 받았어요. (2026.08.06 20:02)

2) 실사용 중 확인된 더 단순한 형식 (한 줄에 "상대방 금액[원] M/D", 방향·시각 없음):
    테니스 6700원 7/3
    이희근 19500 7/3

2번 형식은 방향 표시가 없어 항상 outflow(보냄)로 간주한다 - 이 채널은 보통 모임비/정산을
내 계좌에서 상대에게 보내는 용도로 쓰이기 때문. 받은 건이 섞여 있으면 거래내역 페이지에서
직접 방향을 바로잡아야 한다. 연도도 없어 기준일(보통 오늘) 근처로 추정한다.

상대방이 사람 이름(대화방명)이라 가맹점 기반 분류가 불가능하므로, 여기서 파싱된 건은
항상 "라이프스타일비 > 소셜/네트워킹"으로 기본 배정한다 (분류 로직은 services 계층).
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

_TAGGED_RE = re.compile(
    r"\[(?P<room>[^\]]+)\]\s*"
    r"(?P<amount>[\d,]+)원을\s*"
    r"(?P<direction>보냈어요|받았어요)\.?\s*"
    r"\((?P<date>\d{4}\.\d{2}\.\d{2})\s+(?P<time>\d{2}:\d{2})\)"
)

_LINE_FORMAT_RE = re.compile(
    r"^(?P<room>.+?)\s+(?P<amount>[\d,]+)원?\s+(?P<month>\d{1,2})/(?P<day>\d{1,2})$"
)


class KakaopayParseError(ValueError):
    """카카오페이 송금 형식을 인식하지 못했을 때 발생."""


@dataclass
class ParsedKakaopay:
    room: str
    amount: int
    flow_direction: str  # 'outflow' | 'inflow'
    txn_date: str  # YYYY-MM-DD
    txn_time: Optional[str]  # HH:MM, 형식 2는 시각 정보가 없어 None


def split_messages(raw_text: str) -> list[str]:
    """카카오페이 송금 내역은 보통 한 줄에 한 건씩 붙여넣어진다. 주석(#)/빈 줄은 무시."""
    return [
        line.strip()
        for line in raw_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def parse_kakaopay(text: str, *, reference_date: Optional[date] = None) -> ParsedKakaopay:
    parsed = _parse_tagged_format(text) or _parse_line_format(text, reference_date)
    if parsed is None:
        raise KakaopayParseError(f"카카오페이 송금 형식을 인식할 수 없습니다: {text[:80]!r}")
    return parsed


def _parse_tagged_format(text: str) -> Optional[ParsedKakaopay]:
    normalized = " ".join(text.split())
    match = _TAGGED_RE.search(normalized)
    if not match:
        return None

    direction = "outflow" if match.group("direction") == "보냈어요" else "inflow"
    return ParsedKakaopay(
        room=match.group("room"),
        amount=int(match.group("amount").replace(",", "")),
        flow_direction=direction,
        txn_date=match.group("date").replace(".", "-"),
        txn_time=match.group("time"),
    )


def _parse_line_format(text: str, reference_date: Optional[date]) -> Optional[ParsedKakaopay]:
    normalized = " ".join(text.split())
    match = _LINE_FORMAT_RE.match(normalized)
    if not match:
        return None

    reference_date = reference_date or date.today()
    month, day = int(match.group("month")), int(match.group("day"))
    txn_date = _resolve_year(reference_date, month, day)

    return ParsedKakaopay(
        room=match.group("room").strip(),
        amount=int(match.group("amount").replace(",", "")),
        flow_direction="outflow",
        txn_date=txn_date,
        txn_time=None,
    )


def _resolve_year(reference_date: date, month: int, day: int) -> str:
    """형식 2에는 연도가 없으므로 기준일(보통 오늘) 근처로 연도를 추정한다.

    추정 날짜가 기준일보다 180일 넘게 미래이면 작년 거래를 연말에 뒤늦게 입력하는
    경우로 보고 작년으로 보정한다.
    """
    candidate = date(reference_date.year, month, day)
    if (candidate - reference_date).days > 180:
        candidate = date(reference_date.year - 1, month, day)
    return candidate.isoformat()
