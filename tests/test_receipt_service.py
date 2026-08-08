import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connection as db_connection  # noqa: E402
from app.db.seed_categories import seed_categories  # noqa: E402
from app.services import receipt_service as svc  # noqa: E402
from app.services.category_service import get_category_id  # noqa: E402
from app.services.classification_service import ClassificationRequestError, MerchantClassification  # noqa: E402

CARD_SMS_1 = "[Web발신] 현대카드M 승인 정*구 100,000원 일시불 08/08 09:48 대신주유소 누적669,523원"
CARD_SMS_2 = "[Web발신] 현대카드M 승인 정*구 7,000원 일시불 08/08 09:51 대신주유소 누적676,523원"
KAKAOPAY_SENT = "[모임방A] 6,800원을 보냈어요. (2026.08.06 19:58)"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_ledger.db"
    monkeypatch.setattr(db_connection, "BASE_DIR", tmp_path)
    monkeypatch.setattr(db_connection, "DB_PATH", str(db_file))
    db_connection.init_db()
    seed_categories()
    yield db_connection
    db_connection.get_connection().close()


def test_ingest_card_sms_defaults_to_uncategorized(db):
    result = svc.ingest_card_sms(CARD_SMS_1)
    assert result["status"] == "ok"
    assert result["classified_by"] == "default"

    receipts = svc.list_receipts()
    assert len(receipts) == 1
    assert receipts[0]["major_category"] == "미분류·확인필요"
    assert receipts[0]["merchant_name"] == "대신주유소"
    assert receipts[0]["amount"] == 100000
    assert receipts[0]["review_status"] == "needs_review"


def test_ingest_card_sms_duplicate_is_skipped(db):
    first = svc.ingest_card_sms(CARD_SMS_1)
    second = svc.ingest_card_sms(CARD_SMS_1)
    assert first["status"] == "ok"
    assert second["status"] == "duplicate"
    assert len(svc.list_receipts()) == 1


def test_ingest_card_sms_parse_failure_is_recorded(db):
    result = svc.ingest_card_sms("이건 카드문자가 아님")
    assert result["status"] == "parse_failed"
    assert svc.list_receipts() == []

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT status FROM captures WHERE id = ?", (result["capture_id"],)).fetchone()
    finally:
        conn.close()
    assert row["status"] == "failed"


def test_ingest_kakaopay_defaults_to_social_networking(db):
    result = svc.ingest_kakaopay(KAKAOPAY_SENT)
    assert result["status"] == "ok"

    receipts = svc.list_receipts()
    assert receipts[0]["major_category"] == "라이프스타일비"
    assert receipts[0]["minor_category"] == "소셜/네트워킹"
    assert receipts[0]["flow_direction"] == "outflow"


def test_ingest_card_sms_uses_ai_classification_when_no_rule_matches(db, monkeypatch):
    monkeypatch.setattr(
        svc,
        "classify_merchant",
        lambda *, merchant_name, amount: MerchantClassification(
            major_category="변동비", minor_category="교통·주유", confidence=0.87, raw_response="{}"
        ),
    )

    result = svc.ingest_card_sms(CARD_SMS_1)
    assert result["status"] == "ok"
    assert result["classified_by"] == "ai"

    receipts = svc.list_receipts()
    assert receipts[0]["major_category"] == "변동비"
    assert receipts[0]["minor_category"] == "교통·주유"


def test_ingest_card_sms_ai_returns_uncategorized_falls_back_to_default(db, monkeypatch):
    monkeypatch.setattr(
        svc,
        "classify_merchant",
        lambda *, merchant_name, amount: MerchantClassification(
            major_category=None, minor_category=None, confidence=0.3, raw_response="{}"
        ),
    )

    result = svc.ingest_card_sms(CARD_SMS_1)
    assert result["classified_by"] == "default"
    receipts = svc.list_receipts()
    assert receipts[0]["major_category"] == "미분류·확인필요"


def test_ingest_card_sms_ai_error_falls_back_to_default(db, monkeypatch):
    def _raise(*, merchant_name, amount):
        raise ClassificationRequestError("boom")

    monkeypatch.setattr(svc, "classify_merchant", _raise)

    result = svc.ingest_card_sms(CARD_SMS_1)
    assert result["status"] == "ok"
    assert result["classified_by"] == "default"
    receipts = svc.list_receipts()
    assert receipts[0]["major_category"] == "미분류·확인필요"


def test_reclassify_learns_merchant_rule_and_applies_to_next_capture(db):
    # 1) 처음엔 미분류로 들어옴
    first = svc.ingest_card_sms(CARD_SMS_1)
    traffic_category_id = get_category_id("expense", "변동비", "교통·주유")

    # 2) 사용자가 '대신주유소'를 교통·주유로 재분류 -> merchant_rules에 학습
    svc.reclassify_and_learn(
        receipt_id=first["receipt_id"],
        category_id=traffic_category_id,
        merchant_name="대신주유소",
        source_type="card_sms",
    )

    # 3) 같은 가맹점의 다음 문자는 자동으로 교통·주유로 분류되어야 함
    second = svc.ingest_card_sms(CARD_SMS_2)
    assert second["classified_by"] == "rule"

    receipts = {r["merchant_name"] + str(r["amount"]): r for r in svc.list_receipts()}
    assert receipts["대신주유소100000"]["minor_category"] == "교통·주유"
    assert receipts["대신주유소7000"]["minor_category"] == "교통·주유"
    assert receipts["대신주유소100000"]["review_status"] == "confirmed"


def test_create_manual_entry_bank_transfer_has_no_capture(db):
    category_id = get_category_id("expense", "고정비", "통신비")
    result = svc.create_manual_entry(
        entry_type="expense",
        merchant_name="메리츠07-092",
        amount=20000,
        transaction_date="2026-07-27",
        category_id=category_id,
    )
    assert result["status"] == "ok"

    conn = db.get_connection()
    try:
        row = conn.execute("SELECT capture_id, is_manual_entry FROM receipts WHERE id = ?", (result["receipt_id"],)).fetchone()
    finally:
        conn.close()
    assert row["capture_id"] is None
    assert row["is_manual_entry"] == 1


def test_create_manual_entry_income_pension(db):
    category_id = get_category_id("income", "수입", "연금인출유입")
    result = svc.create_manual_entry(
        entry_type="income",
        merchant_name=None,
        amount=1500000,
        transaction_date="2026-08-01",
        category_id=category_id,
    )
    receipts = svc.list_receipts(entry_type="income")
    assert len(receipts) == 1
    assert receipts[0]["flow_direction"] == "inflow"
    assert receipts[0]["minor_category"] == "연금인출유입"


def test_summary_counts(db):
    svc.ingest_card_sms(CARD_SMS_1)
    svc.ingest_kakaopay(KAKAOPAY_SENT)
    counts = svc.summary_counts()
    assert counts["total_receipts"] == 2
    assert counts["needs_review"] == 2


def test_list_receipts_for_month_filters_and_orders_by_date(db):
    category_id = get_category_id("income", "수입", "연금인출유입")
    svc.create_manual_entry(
        entry_type="income", merchant_name=None, amount=1000, transaction_date="2026-07-15", category_id=category_id
    )
    svc.create_manual_entry(
        entry_type="income", merchant_name=None, amount=2000, transaction_date="2026-08-01", category_id=category_id
    )
    svc.create_manual_entry(
        entry_type="income", merchant_name=None, amount=3000, transaction_date="2026-08-20", category_id=category_id
    )

    rows = svc.list_receipts_for_month("2026-08")
    assert [r["amount"] for r in rows] == [2000, 3000]
    assert all(r["transaction_date"].startswith("2026-08") for r in rows)
