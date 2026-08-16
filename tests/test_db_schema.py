"""1단계 DB 스키마 검증 테스트.

임시 SQLite 파일에 스키마를 생성해 실제 프로젝트 DB(data/ledger.db)에는 손대지 않는다.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connection as db_connection  # noqa: E402
from app.db.seed_categories import CATEGORY_SEED, seed_categories  # noqa: E402

EXPECTED_TABLES = {
    "categories",
    "captures",
    "ocr_results",
    "receipts",
    "classifications",
    "merchant_rules",
}

EXPECTED_EXPENSE_MAJORS = {
    "고정비",
    "변동비",
    "라이프스타일비",
    "가족·경조사비",
    "비정기 대형지출",
    "미분류·확인필요",
}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """각 테스트마다 독립된 임시 DB 파일을 사용하도록 connection 모듈을 패치한다."""
    db_file = tmp_path / "test_ledger.db"
    monkeypatch.setattr(db_connection, "BASE_DIR", tmp_path)
    monkeypatch.setattr(db_connection, "DB_PATH", str(db_file))
    monkeypatch.setattr(db_connection, "SUPABASE_DB_URL", None)
    db_connection.init_db()
    yield db_connection
    db_connection.get_connection().close()


def test_init_db_creates_all_tables(db):
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r["name"] for r in rows}
    finally:
        conn.close()
    assert EXPECTED_TABLES.issubset(table_names)


def test_init_db_is_idempotent(db):
    # 이미 테이블이 있는 상태에서 다시 실행해도 에러 없이 통과해야 함
    db.init_db()
    db.init_db()


def test_seed_categories_matches_brief(db):
    inserted = seed_categories()
    assert inserted == len(CATEGORY_SEED)

    conn = db.get_connection()
    try:
        majors = {
            r["major_category"]
            for r in conn.execute(
                "SELECT DISTINCT major_category FROM categories WHERE entry_type='expense'"
            )
        }
        income_minors = {
            r["minor_category"]
            for r in conn.execute(
                "SELECT minor_category FROM categories WHERE entry_type='income'"
            )
        }
    finally:
        conn.close()

    assert majors == EXPECTED_EXPENSE_MAJORS
    assert income_minors == {"연금인출유입", "기타수입", "급여", "아르바이트", "실업급여", "실손보험", "모임정산"}


def test_seed_categories_is_idempotent(db):
    first = seed_categories()
    second = seed_categories()
    assert first == len(CATEGORY_SEED)
    assert second == 0  # 이미 있는 카테고리는 재삽입되지 않음


def test_kakaopay_default_category_exists(db):
    seed_categories()
    conn = db.get_connection()
    try:
        row = conn.execute(
            """
            SELECT id FROM categories
            WHERE entry_type='expense' AND major_category='라이프스타일비' AND minor_category='소셜/네트워킹'
            """
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_no_pension_or_investment_tables(db):
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r["name"] for r in rows}
    finally:
        conn.close()
    forbidden_keywords = ("pension", "invest", "irp", "연금계좌", "투자")
    for name in table_names:
        for kw in forbidden_keywords:
            assert kw not in name.lower()


def test_capture_to_receipt_flow_and_fk(db):
    seed_categories()
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO captures (source_type, raw_text) VALUES ('card_sms', ?)",
            ("[Web발신] 현대카드M 승인 정*구 100,000원 일시불 08/08 09:48 대신주유소 누적669,523원",),
        )
        capture_id = cur.lastrowid

        cur = conn.execute(
            """
            INSERT INTO ocr_results
                (capture_id, engine, merchant_name, amount, txn_date, txn_time, flow_direction, status)
            VALUES (?, 'regex_card_sms', '대신주유소', 100000, '2026-08-08', '09:48', 'outflow', 'success')
            """,
            (capture_id,),
        )
        ocr_result_id = cur.lastrowid

        cur = conn.execute(
            """
            INSERT INTO receipts
                (capture_id, ocr_result_id, entry_type, source_type, flow_direction,
                 merchant_name, amount, transaction_date, transaction_time)
            VALUES (?, ?, 'expense', 'card_sms', 'outflow', '대신주유소', 100000, '2026-08-08', '09:48')
            """,
            (capture_id, ocr_result_id),
        )
        receipt_id = cur.lastrowid

        category_id = conn.execute(
            "SELECT id FROM categories WHERE major_category='변동비' AND minor_category='교통·주유'"
        ).fetchone()["id"]

        conn.execute(
            """
            INSERT INTO classifications (receipt_id, category_id, classified_by, confidence, is_current)
            VALUES (?, ?, 'ai', 0.92, 1)
            """,
            (receipt_id, category_id),
        )
        conn.commit()

        joined = conn.execute(
            """
            SELECT r.merchant_name, c.major_category, c.minor_category
            FROM receipts r
            JOIN classifications cl ON cl.receipt_id = r.id AND cl.is_current = 1
            JOIN categories c ON c.id = cl.category_id
            WHERE r.id = ?
            """,
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()

    assert joined["merchant_name"] == "대신주유소"
    assert joined["major_category"] == "변동비"
    assert joined["minor_category"] == "교통·주유"


def test_bank_manual_entry_without_capture(db):
    """은행이체는 자동 파싱 대상이 아니므로 capture_id 없이 receipts에 직접 들어갈 수 있어야 한다."""
    seed_categories()
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO receipts
                (capture_id, entry_type, source_type, flow_direction,
                 merchant_name, amount, transaction_date, is_manual_entry, review_status)
            VALUES (NULL, 'expense', 'bank_manual', 'outflow', '메리츠07-092', 20000, '2026-07-27', 1, 'confirmed')
            """
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM receipts WHERE source_type='bank_manual'"
        ).fetchone()
    finally:
        conn.close()
    assert row["capture_id"] is None
    assert row["is_manual_entry"] == 1


def test_only_one_current_classification_per_receipt(db):
    seed_categories()
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO receipts
                (entry_type, source_type, flow_direction, amount, transaction_date)
            VALUES ('expense', 'kakaopay', 'outflow', 6800, '2026-08-06')
            """
        )
        receipt_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        category_id = conn.execute(
            "SELECT id FROM categories WHERE minor_category='소셜/네트워킹'"
        ).fetchone()["id"]

        conn.execute(
            "INSERT INTO classifications (receipt_id, category_id, classified_by, is_current) VALUES (?, ?, 'default', 1)",
            (receipt_id, category_id),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO classifications (receipt_id, category_id, classified_by, is_current) VALUES (?, ?, 'user', 1)",
                (receipt_id, category_id),
            )
            conn.commit()
    finally:
        conn.close()


def test_dining_category_split_migrates_existing_classifications(db):
    """식비(외식·배달) 분리 이전에 이미 배포된 DB를 흉내낸다: 옛 카테고리가 있고 그걸로
    분류된 거래가 있는 상태에서 seed_categories()를 실행하면 식비(외식)으로 옮겨가고,
    옛 카테고리는 목록에서 사라져야 한다(재삽입/삭제 아님, is_active=0)."""
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO categories (entry_type, major_category, minor_category, sort_order) "
            "VALUES ('expense', '변동비', '식비(외식·배달)', 20)"
        )
        old_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

        conn.execute(
            "INSERT INTO receipts (entry_type, source_type, flow_direction, merchant_name, amount, transaction_date) "
            "VALUES ('expense', 'card_sms', 'outflow', '스타벅스', 5000, '2026-07-01')"
        )
        receipt_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute(
            "INSERT INTO classifications (receipt_id, category_id, classified_by, is_current) VALUES (?, ?, 'default', 1)",
            (receipt_id, old_id),
        )
        conn.commit()
    finally:
        conn.close()

    seed_categories()

    conn = db.get_connection()
    try:
        old_row = conn.execute("SELECT is_active FROM categories WHERE id = ?", (old_id,)).fetchone()
        joined = conn.execute(
            """
            SELECT c.major_category, c.minor_category
            FROM classifications cl JOIN categories c ON c.id = cl.category_id
            WHERE cl.receipt_id = ? AND cl.is_current = 1
            """,
            (receipt_id,),
        ).fetchone()
    finally:
        conn.close()

    assert old_row["is_active"] == 0
    assert joined["major_category"] == "변동비"
    assert joined["minor_category"] == "식비(외식)"


def test_invalid_category_fk_rejected(db):
    seed_categories()
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO receipts
                (entry_type, source_type, flow_direction, amount, transaction_date)
            VALUES ('expense', 'card_sms', 'outflow', 1000, '2026-08-08')
            """
        )
        receipt_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO classifications (receipt_id, category_id, classified_by, is_current) VALUES (?, 999999, 'ai', 1)",
                (receipt_id,),
            )
            conn.commit()
    finally:
        conn.close()
