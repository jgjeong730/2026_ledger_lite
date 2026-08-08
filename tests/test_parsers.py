import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parsers.card_sms_parser import (  # noqa: E402
    CardSmsParseError,
    parse_card_sms,
    split_messages as split_card_sms_messages,
)
from app.parsers.kakaopay_parser import (  # noqa: E402
    KakaopayParseError,
    parse_kakaopay,
    split_messages as split_kakaopay_messages,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_split_card_sms_fixture_yields_three_messages():
    raw = (FIXTURES_DIR / "card_sms" / "card_sms_samples.txt").read_text(encoding="utf-8")
    messages = split_card_sms_messages(raw)
    assert len(messages) == 3


def test_parse_card_sms_fixture_samples():
    raw = (FIXTURES_DIR / "card_sms" / "card_sms_samples.txt").read_text(encoding="utf-8")
    messages = split_card_sms_messages(raw)
    parsed = [parse_card_sms(m, reference_date=date(2026, 8, 8)) for m in messages]

    assert parsed[0].merchant == "대신주유소"
    assert parsed[0].amount == 100000
    assert parsed[0].txn_date == "2026-08-08"
    assert parsed[0].txn_time == "09:48"
    assert parsed[0].company == "현대카드M"
    assert parsed[0].installment == "일시불"
    assert parsed[0].cumulative_amount == 669523

    assert parsed[1].amount == 7000
    assert parsed[2].merchant == "경북상회"
    assert parsed[2].amount == 10000


def test_parse_card_sms_infers_year_from_reference_date():
    text = "[Web발신] 신한카드 승인 홍*동 5,000원 일시불 01/02 08:00 스타벅스 누적10,000원"
    parsed = parse_card_sms(text, reference_date=date(2026, 8, 8))
    assert parsed.txn_date == "2027-01-02" or parsed.txn_date == "2026-01-02"
    # 8/8 기준 1/2는 과거이므로 올해로 취급되어야 함 (미래로 180일 넘게 벌어지지 않음)
    assert parsed.txn_date == "2026-01-02"


def test_parse_card_sms_rolls_back_year_when_far_in_future():
    # 기준일이 1월 초인데 문자 날짜가 12월이면 작년 거래로 간주
    text = "[Web발신] 신한카드 승인 홍*동 5,000원 일시불 12/30 08:00 스타벅스 누적10,000원"
    parsed = parse_card_sms(text, reference_date=date(2026, 1, 5))
    assert parsed.txn_date == "2025-12-30"


def test_parse_card_sms_invalid_format_raises():
    with pytest.raises(CardSmsParseError):
        parse_card_sms("이것은 카드 승인문자가 아닙니다")


def test_split_kakaopay_fixture_yields_two_messages():
    raw = (FIXTURES_DIR / "kakaopay" / "kakaopay_samples.txt").read_text(encoding="utf-8")
    messages = split_kakaopay_messages(raw)
    assert len(messages) == 2


def test_parse_kakaopay_fixture_samples():
    raw = (FIXTURES_DIR / "kakaopay" / "kakaopay_samples.txt").read_text(encoding="utf-8")
    messages = split_kakaopay_messages(raw)
    parsed = [parse_kakaopay(m) for m in messages]

    assert parsed[0].room == "모임방A"
    assert parsed[0].amount == 6800
    assert parsed[0].flow_direction == "outflow"
    assert parsed[0].txn_date == "2026-08-06"
    assert parsed[0].txn_time == "19:58"

    assert parsed[1].flow_direction == "inflow"


def test_parse_kakaopay_invalid_format_raises():
    with pytest.raises(KakaopayParseError):
        parse_kakaopay("이것은 카카오페이 송금 메시지가 아닙니다")
