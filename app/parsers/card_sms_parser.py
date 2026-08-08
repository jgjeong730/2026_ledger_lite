"""카드 승인문자 정규식 파서.

샘플 형식 (tests/fixtures/card_sms/card_sms_samples.txt):
    [Web발신] 현대카드M 승인 정*구 100,000원 일시불 08/08 09:48 대신주유소 누적669,523원

카드사마다 표현이 조금씩 다를 수 있지만 "카드사 승인 이름 금액원 할부구분 MM/DD HH:MM 가맹점 누적N원"
골격은 공통이라고 가정한다. AI 없이 정규식만으로 파싱하며, 가맹점 기반 카테고리 분류는
merchant_rules/AI(4단계) 몫이다.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

_MESSAGE_START_RE = re.compile(r"(?=\[Web발신\])")

_CARD_SMS_RE = re.compile(
    r"\[Web발신\]\s*"
    r"(?P<company>\S+)\s+승인\s+"
    r"(?P<holder>\S+)\s+"
    r"(?P<amount>[\d,]+)원\s+"
    r"(?P<installment>\S+)\s+"
    r"(?P<date>\d{2}/\d{2})\s+"
    r"(?P<time>\d{2}:\d{2})\s+"
    r"(?P<merchant>.+?)\s+"
    r"누적(?P<cumulative>[\d,]+)원"
)


class CardSmsParseError(ValueError):
    """카드 승인문자 형식을 인식하지 못했을 때 발생."""


@dataclass
class ParsedCardSms:
    company: str
    holder: str
    amount: int
    installment: str
    txn_date: str  # YYYY-MM-DD
    txn_time: str  # HH:MM
    merchant: str
    cumulative_amount: int


def split_messages(raw_text: str) -> list[str]:
    """붙여넣은 텍스트를 [Web발신] 기준으로 개별 메시지 블록으로 분리한다.

    실제 문자 앱에서 복사하면 메시지 한 건이 여러 줄로 나뉘어 있을 수 있으므로,
    다음 [Web발신]이 나오기 전까지를 한 블록으로 취급한다. '#'으로 시작하는 주석 줄(픽스처
    파일의 안내문 등)은 무시한다.
    """
    cleaned = "\n".join(
        line for line in raw_text.splitlines() if not line.strip().startswith("#")
    )
    blocks = [b.strip() for b in _MESSAGE_START_RE.split(cleaned) if b.strip()]
    return [b for b in blocks if b.startswith("[Web발신]")]


def parse_card_sms(text: str, *, reference_date: Optional[date] = None) -> ParsedCardSms:
    """카드 승인문자 한 건을 파싱한다. 형식이 다르면 CardSmsParseError."""
    normalized = " ".join(text.split())
    match = _CARD_SMS_RE.search(normalized)
    if not match:
        raise CardSmsParseError(f"카드 승인문자 형식을 인식할 수 없습니다: {text[:80]!r}")

    reference_date = reference_date or date.today()
    month, day = (int(p) for p in match.group("date").split("/"))
    txn_date = _resolve_year(reference_date, month, day)

    return ParsedCardSms(
        company=match.group("company"),
        holder=match.group("holder"),
        amount=int(match.group("amount").replace(",", "")),
        installment=match.group("installment"),
        txn_date=txn_date,
        txn_time=match.group("time"),
        merchant=match.group("merchant").strip(),
        cumulative_amount=int(match.group("cumulative").replace(",", "")),
    )


def _resolve_year(reference_date: date, month: int, day: int) -> str:
    """카드문자에는 연도가 없으므로 기준일(보통 오늘) 근처로 연도를 추정한다.

    추정 날짜가 기준일보다 180일 넘게 미래이면 작년 거래를 연말에 뒤늦게 입력하는
    경우로 보고 작년으로 보정한다.
    """
    candidate = date(reference_date.year, month, day)
    if (candidate - reference_date).days > 180:
        candidate = date(reference_date.year - 1, month, day)
    return candidate.isoformat()
