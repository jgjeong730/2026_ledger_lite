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


LINE_FORMAT_SAMPLE = (
    "다이소아성산업\n15,000원\n현대카드M\n일시불\n2026.07.01 20:43\n"
    "\n"
    "이마트에브리데이수원태장점\n17,170원\n현대카드M\n일시불\n2026.07.01 20:58"
)


def test_split_card_sms_line_format_without_web_tag_yields_two_messages():
    messages = split_card_sms_messages(LINE_FORMAT_SAMPLE)
    assert len(messages) == 2


def test_parse_card_sms_line_format_without_web_tag():
    messages = split_card_sms_messages(LINE_FORMAT_SAMPLE)
    parsed = [parse_card_sms(m) for m in messages]

    assert parsed[0].merchant == "다이소아성산업"
    assert parsed[0].amount == 15000
    assert parsed[0].company == "현대카드M"
    assert parsed[0].installment == "일시불"
    assert parsed[0].txn_date == "2026-07-01"
    assert parsed[0].txn_time == "20:43"

    assert parsed[1].merchant == "이마트에브리데이수원태장점"
    assert parsed[1].amount == 17170
    assert parsed[1].txn_time == "20:58"


def test_split_card_sms_handles_mixed_tagged_and_line_format_in_one_paste():
    mixed = (
        "[Web발신] 현대카드M 승인 정*구 100,000원 일시불 08/08 09:48 대신주유소 누적669,523원\n"
        "\n"
        "다이소아성산업\n15,000원\n현대카드M\n일시불\n2026.07.01 20:43"
    )
    messages = split_card_sms_messages(mixed)
    assert len(messages) == 2

    parsed = [parse_card_sms(m, reference_date=date(2026, 8, 8)) for m in messages]
    assert parsed[0].merchant == "대신주유소"
    assert parsed[0].cumulative_amount == 669523
    assert parsed[1].merchant == "다이소아성산업"
    assert parsed[1].txn_date == "2026-07-01"


QUICK_FORMAT_SAMPLE = (
    "7/1 쿠팡이츠 11000\n"
    "7/2 쿠팡이츠 24300\n"
    "7/4 쿠팡 42220\n"
    "7/5 쿠팡 4980"
)


def test_split_card_sms_quick_format_yields_one_message_per_line():
    messages = split_card_sms_messages(QUICK_FORMAT_SAMPLE)
    assert len(messages) == 4


def test_parse_card_sms_quick_format():
    messages = split_card_sms_messages(QUICK_FORMAT_SAMPLE)
    parsed = [parse_card_sms(m, reference_date=date(2026, 8, 10)) for m in messages]

    assert parsed[0].merchant == "쿠팡이츠"
    assert parsed[0].amount == 11000
    assert parsed[0].txn_date == "2026-07-01"
    assert parsed[0].txn_time is None
    assert parsed[0].company == ""

    assert parsed[2].merchant == "쿠팡"
    assert parsed[2].amount == 42220


def test_split_card_sms_quick_format_mixed_with_tagged_paragraph():
    mixed = (
        "[Web발신] 현대카드M 승인 정*구 100,000원 일시불 08/08 09:48 대신주유소 누적669,523원\n"
        "\n"
        "7/1 쿠팡이츠 11000\n"
        "7/2 쿠팡 42220"
    )
    messages = split_card_sms_messages(mixed)
    assert len(messages) == 3

    parsed = [parse_card_sms(m, reference_date=date(2026, 8, 10)) for m in messages]
    assert parsed[0].merchant == "대신주유소"
    assert parsed[1].merchant == "쿠팡이츠"
    assert parsed[2].merchant == "쿠팡"


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


def test_split_kakaopay_line_format_yields_one_message_per_line():
    raw = "테니스 6700원 7/3\n이희근 19500 7/3\n애플서비스 1100 7/14"
    messages = split_kakaopay_messages(raw)
    assert len(messages) == 3


def test_parse_kakaopay_line_format_without_tag():
    parsed = parse_kakaopay("테니스 6700원 7/3", reference_date=date(2026, 8, 9))
    assert parsed.room == "테니스"
    assert parsed.amount == 6700
    assert parsed.flow_direction == "outflow"
    assert parsed.txn_date == "2026-07-03"
    assert parsed.txn_time is None


def test_parse_kakaopay_line_format_amount_without_won_suffix():
    parsed = parse_kakaopay("이희근 19500 7/3", reference_date=date(2026, 8, 9))
    assert parsed.room == "이희근"
    assert parsed.amount == 19500
