"""카카오페이 송금(1/N 정산) 정규식 파서.

샘플 형식 (tests/fixtures/kakaopay/kakaopay_samples.txt):
    [모임방A] 6,800원을 보냈어요. (2026.08.06 19:58)
    [모임방A] 6,800원을 받았어요. (2026.08.06 20:02)

상대방이 사람 이름(대화방명)이라 가맹점 기반 분류가 불가능하므로, 여기서 파싱된 건은
항상 "라이프스타일비 > 소셜/네트워킹"으로 기본 배정한다 (분류 로직은 services 계층).
"""

import re
from dataclasses import dataclass

_KAKAOPAY_RE = re.compile(
    r"\[(?P<room>[^\]]+)\]\s*"
    r"(?P<amount>[\d,]+)원을\s*"
    r"(?P<direction>보냈어요|받았어요)\.?\s*"
    r"\((?P<date>\d{4}\.\d{2}\.\d{2})\s+(?P<time>\d{2}:\d{2})\)"
)


class KakaopayParseError(ValueError):
    """카카오페이 송금 형식을 인식하지 못했을 때 발생."""


@dataclass
class ParsedKakaopay:
    room: str
    amount: int
    flow_direction: str  # 'outflow' | 'inflow'
    txn_date: str  # YYYY-MM-DD
    txn_time: str  # HH:MM


def split_messages(raw_text: str) -> list[str]:
    """카카오페이 송금 내역은 보통 한 줄에 한 건씩 붙여넣어진다. 주석(#)/빈 줄은 무시."""
    return [
        line.strip()
        for line in raw_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def parse_kakaopay(text: str) -> ParsedKakaopay:
    normalized = " ".join(text.split())
    match = _KAKAOPAY_RE.search(normalized)
    if not match:
        raise KakaopayParseError(f"카카오페이 송금 형식을 인식할 수 없습니다: {text[:80]!r}")

    direction = "outflow" if match.group("direction") == "보냈어요" else "inflow"

    return ParsedKakaopay(
        room=match.group("room"),
        amount=int(match.group("amount").replace(",", "")),
        flow_direction=direction,
        txn_date=match.group("date").replace(".", "-"),
        txn_time=match.group("time"),
    )
