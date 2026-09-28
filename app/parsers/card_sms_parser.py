"""카드 승인문자 정규식 파서.

세 가지 실제 형식을 지원한다:

1) 통신사 [Web발신] 태그가 붙는 한 줄짜리 문자 (일부 카드사/통신사 조합):
    [Web발신] 현대카드M 승인 정*구 100,000원 일시불 08/08 09:48 대신주유소 누적669,523원

2) [Web발신] 태그 없이 항목이 줄바꿈으로 나뉘는 문자 (카드 앱 상세 내역 복붙, 연도가
   포함되어 있어 기준일 추정이 필요 없다):
    다이소아성산업
    15,000원
    현대카드M
    일시불
    2026.07.01 20:43

3) 빠른 수기입력용 축약형 - 한 줄에 "월/일 가맹점 금액"만 (연도·카드사·할부구분 없음,
   여러 건을 줄바꿈만으로 죽 이어 붙여도 한 줄씩 개별 처리된다). "가맹점 금액 월/일"처럼
   날짜가 맨 뒤에 오는 순서도 함께 지원한다:
    7/1 쿠팡이츠 11000
    쿠팡이츠 24300 7/2

카드사/통신사마다 표현이 다를 수 있어 세 형식을 순서대로 시도하고, 다 안 맞으면
CardSmsParseError를 던진다. AI 없이 정규식만으로 파싱하며, 가맹점 기반 카테고리 분류는
merchant_rules/AI(4단계) 몫이다.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

_MESSAGE_START_RE = re.compile(r"(?=\[Web발신\])")

_CARD_SMS_RE = re.compile(
    r"\[Web발신\]\s*"
    r"(?P<company>.+?)\s+승인\s+"
    r"(?P<holder>\S+)\s+"
    r"(?P<amount>[\d,]+)원\s+"
    r"(?P<installment>\S+)\s+"
    r"(?P<date>\d{2}/\d{2})\s+"
    r"(?P<time>\d{2}:\d{2})\s+"
    r"(?P<merchant>.+?)\s+"
    r"누적(?P<cumulative>[\d,]+)원"
)

# [Web발신] 태그 없이 "가맹점 / 금액 / 카드사 / 할부구분 / YYYY.MM.DD HH:MM" 5줄로 오는 형식.
# 각 줄을 그대로 필드로 대응시킨다 (홀더명/누적금액은 이 형식에 없음).
_AMOUNT_LINE_RE = re.compile(r"^([\d,]+)원$")
_DATETIME_LINE_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}:\d{2})$")

# "월/일 가맹점 금액[원]" 한 줄 축약형. 가맹점명에 공백이 있어도 되도록 비탐욕 매칭.
_QUICK_LINE_RE = re.compile(r"^(?P<month>\d{1,2})/(?P<day>\d{1,2})\s+(?P<merchant>.+?)\s+(?P<amount>[\d,]+)원?$")
# 날짜/금액/가맹점 순서의 간편 입력도 지원한다. 예: `9/23 20,960 쿠팡`
_QUICK_LINE_DATE_AMOUNT_RE = re.compile(
    r"^(?P<month>\d{1,2})/(?P<day>\d{1,2})\s+"
    r"(?P<amount>[\d,]+)원?\s+(?P<merchant>.+?)$"
)
# "가맹점 금액[원] 월/일" - 날짜가 맨 뒤에 오는 축약형 (날짜를 마지막에 입력하는 사용 습관 지원).
_QUICK_LINE_TRAILING_DATE_RE = re.compile(
    r"^(?P<merchant>.+?)\s+(?P<amount>[\d,]+)원?\s+(?P<month>\d{1,2})/(?P<day>\d{1,2})$"
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
    txn_time: Optional[str]  # HH:MM, 형식 3은 시각 정보가 없어 None
    merchant: str
    cumulative_amount: int


def split_messages(raw_text: str) -> list[str]:
    """붙여넣은 텍스트를 개별 메시지 블록으로 분리한다. 여러 형식이 한 번에 섞여
    붙여넣어져도(카드 사용 직후 오는 [Web발신] 문자 + 카드 앱 상세 내역 + 축약 수기입력)
    모두 처리한다.

    먼저 빈 줄 기준으로 문단을 나눈 뒤, 문단별로:
    - [Web발신] 태그가 있으면 그 태그 기준으로 다시 나누고(문자 한 건이 여러 줄에 걸쳐
      있거나 여러 건이 빈 줄 없이 붙어 있을 수 있으므로)
    - 문단의 모든 줄이 축약형("월/일 가맹점 금액")이면 한 줄씩 개별 블록으로 나누고
      (빈 줄 없이 죽 이어 붙여 넣는 게 이 형식의 특징이므로)
    - 그 외에는 문단 전체를 한 블록(줄바꿈으로만 구분되는 카드 앱 상세 형식)으로 취급한다.

    '#'으로 시작하는 주석 줄(픽스처 파일의 안내문 등)은 무시한다.
    """
    # 일부 복사/전달 경로에서는 줄바꿈이 실제 개행이 아닌 리터럴 `\n`으로 들어온다.
    # 두 입력을 동일하게 처리해 여러 건을 한 메시지로 오인하지 않도록 한다.
    normalized_text = raw_text.replace("\\r\\n", "\n").replace("\\n", "\n")
    cleaned = "\n".join(
        line for line in normalized_text.splitlines() if not line.strip().startswith("#")
    )
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned.strip()) if p.strip()]

    blocks: list[str] = []
    for para in paragraphs:
        if "[Web발신]" in para:
            tagged = [b.strip() for b in _MESSAGE_START_RE.split(para) if b.strip()]
            blocks.extend(b for b in tagged if b.startswith("[Web발신]"))
            continue

        lines = [line.strip() for line in para.splitlines() if line.strip()]
        if lines and all(_is_quick_line(line) for line in lines):
            blocks.extend(lines)
        else:
            blocks.append(para)
    return blocks


def _is_quick_line(line: str) -> bool:
    return bool(
        _QUICK_LINE_RE.match(line)
        or _QUICK_LINE_DATE_AMOUNT_RE.match(line)
        or _QUICK_LINE_TRAILING_DATE_RE.match(line)
    )


def parse_card_sms(text: str, *, reference_date: Optional[date] = None) -> ParsedCardSms:
    """카드 승인문자 한 건을 파싱한다. 세 형식을 순서대로 시도하고, 다 안 맞으면 CardSmsParseError."""
    parsed = (
        _parse_tagged_format(text, reference_date)
        or _parse_line_format(text)
        or _parse_quick_format(text, reference_date)
    )
    if parsed is None:
        raise CardSmsParseError(f"카드 승인문자 형식을 인식할 수 없습니다: {text[:80]!r}")
    return parsed


def _parse_tagged_format(text: str, reference_date: Optional[date]) -> Optional[ParsedCardSms]:
    normalized = " ".join(text.split())
    match = _CARD_SMS_RE.search(normalized)
    if not match:
        return None

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


def _parse_line_format(text: str) -> Optional[ParsedCardSms]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 5:
        return None
    merchant, amount_line, company, installment, datetime_line = lines

    amount_match = _AMOUNT_LINE_RE.match(amount_line)
    dt_match = _DATETIME_LINE_RE.match(datetime_line)
    if not amount_match or not dt_match:
        return None

    year, month, day, time_str = dt_match.groups()
    return ParsedCardSms(
        company=company,
        holder="",
        amount=int(amount_match.group(1).replace(",", "")),
        installment=installment,
        txn_date=f"{year}-{month}-{day}",
        txn_time=time_str,
        merchant=merchant,
        cumulative_amount=0,
    )


def _parse_quick_format(text: str, reference_date: Optional[date]) -> Optional[ParsedCardSms]:
    stripped = text.strip()
    match = (
        _QUICK_LINE_RE.match(stripped)
        or _QUICK_LINE_DATE_AMOUNT_RE.match(stripped)
        or _QUICK_LINE_TRAILING_DATE_RE.match(stripped)
    )
    if not match:
        return None

    reference_date = reference_date or date.today()
    month, day = int(match.group("month")), int(match.group("day"))
    txn_date = _resolve_year(reference_date, month, day)

    return ParsedCardSms(
        company="",
        holder="",
        amount=int(match.group("amount").replace(",", "")),
        installment="",
        txn_date=txn_date,
        txn_time=None,
        merchant=match.group("merchant").strip(),
        cumulative_amount=0,
    )


def _resolve_year(reference_date: date, month: int, day: int) -> str:
    """[Web발신] 태그 형식/축약형에는 연도가 없으므로 기준일(보통 오늘) 근처로 연도를 추정한다.

    추정 날짜가 기준일보다 180일 넘게 미래이면 작년 거래를 연말에 뒤늦게 입력하는
    경우로 보고 작년으로 보정한다.
    """
    candidate = date(reference_date.year, month, day)
    if (candidate - reference_date).days > 180:
        candidate = date(reference_date.year - 1, month, day)
    return candidate.isoformat()
