import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connection as db_connection  # noqa: E402
from app.db.seed_categories import seed_categories  # noqa: E402
from app.services import dashboard_service as dash  # noqa: E402
from app.services.category_service import get_category_id, get_uncategorized_category_id  # noqa: E402
from app.services.receipt_service import create_manual_entry  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_ledger.db"
    monkeypatch.setattr(db_connection, "BASE_DIR", tmp_path)
    monkeypatch.setattr(db_connection, "DB_PATH", str(db_file))
    monkeypatch.setattr(db_connection, "SUPABASE_DB_URL", None)
    db_connection.init_db()
    seed_categories()
    yield db_connection
    db_connection.get_connection().close()


def _seed_sample_data():
    traffic = get_category_id("expense", "변동비", "교통·주유")
    social = get_category_id("expense", "라이프스타일비", "소셜/네트워킹")
    uncategorized = get_uncategorized_category_id()
    pension = get_category_id("income", "수입", "연금인출유입")
    food = get_category_id("expense", "변동비", "식비(외식)")

    # 2026-08: 지출 3건(교통 10만, 소셜 6800, 미분류 5000) + 수입 1건(150만)
    create_manual_entry(
        entry_type="expense", merchant_name="대신주유소", amount=100000,
        transaction_date="2026-08-08", category_id=traffic,
    )
    create_manual_entry(
        entry_type="expense", merchant_name="모임방A", amount=6800,
        transaction_date="2026-08-06", category_id=social,
    )
    create_manual_entry(
        entry_type="expense", merchant_name="이름모를가게", amount=5000,
        transaction_date="2026-08-05", category_id=uncategorized,
    )
    create_manual_entry(
        entry_type="income", merchant_name=None, amount=1500000,
        transaction_date="2026-08-01", category_id=pension,
    )
    # 2026-07: 지출 1건(식비 2만)
    create_manual_entry(
        entry_type="expense", merchant_name="맛집", amount=20000,
        transaction_date="2026-07-15", category_id=food,
    )


def test_available_months_sorted_desc(db):
    _seed_sample_data()
    assert dash.available_months() == ["2026-08", "2026-07"]


def test_monthly_summary(db):
    _seed_sample_data()
    summary = dash.monthly_summary("2026-08")
    assert summary["expense"] == 100000 + 6800 + 5000
    assert summary["income"] == 1500000
    assert summary["net"] == 1500000 - (100000 + 6800 + 5000)
    assert summary["receipt_count"] == 4


def test_monthly_summary_needs_review_excludes_manual_entries(db):
    # create_manual_entry는 항상 review_status='confirmed'로 등록되므로 확인 필요는 0건이어야 함
    _seed_sample_data()
    summary = dash.monthly_summary("2026-08")
    assert summary["needs_review"] == 0


def test_expense_by_major_category(db):
    _seed_sample_data()
    rows = {r["major_category"]: r["amount"] for r in dash.expense_by_major_category("2026-08")}
    assert rows["변동비"] == 100000
    assert rows["라이프스타일비"] == 6800
    assert rows["미분류·확인필요"] == 5000
    # 금액 내림차순 정렬 확인
    amounts = [r["amount"] for r in dash.expense_by_major_category("2026-08")]
    assert amounts == sorted(amounts, reverse=True)


def test_expense_by_category_includes_uncategorized_and_reconciles_total(db):
    _seed_sample_data()
    rows = dash.expense_by_category("2026-08")
    total = sum(r["amount"] for r in rows)
    assert total == dash.monthly_summary("2026-08")["expense"]

    uncategorized = next(r for r in rows if r["major_category"] == "미분류·확인필요")
    assert uncategorized["minor_category"] == ""
    assert uncategorized["amount"] == 5000


def test_expense_by_category_limit(db):
    _seed_sample_data()
    rows = dash.expense_by_category("2026-08", limit=1)
    assert len(rows) == 1
    assert rows[0]["amount"] == 100000  # 가장 큰 금액


def test_monthly_trend_oldest_to_newest(db):
    _seed_sample_data()
    trend = dash.monthly_trend(6)
    months = [t["month"] for t in trend]
    assert months == ["2026-07", "2026-08"]

    july = trend[0]
    august = trend[1]
    assert july["expense"] == 20000
    assert july["income"] == 0
    assert august["expense"] == 100000 + 6800 + 5000
    assert august["income"] == 1500000


def test_empty_db_returns_empty_results(db):
    assert dash.available_months() == []
    assert dash.expense_by_major_category("2026-08") == []
    assert dash.expense_by_category("2026-08") == []
    assert dash.monthly_trend(6) == []
    summary = dash.monthly_summary("2026-08")
    assert summary == {"expense": 0, "income": 0, "net": 0, "needs_review": 0, "receipt_count": 0}


def test_build_monthly_report_text_includes_summary_and_categories(db):
    _seed_sample_data()
    text = dash.build_monthly_report_text("2026-08")

    assert "2026-08" in text
    assert "111,800원" in text  # 지출 합계 (100000+6800+5000)
    assert "1,500,000원" in text  # 수입 합계
    assert "변동비: 100,000원" in text
    assert "라이프스타일비: 6,800원" in text
    assert "미분류·확인필요: 5,000원" in text


def test_build_monthly_report_text_empty_month_still_returns_text(db):
    text = dash.build_monthly_report_text("2026-08")
    assert "2026-08" in text
    assert "지출 0원" in text


def test_available_weeks_returns_monday_start_dates_desc(db):
    _seed_sample_data()
    # 2026-08-08(토)이 속한 주의 월요일은 2026-08-03, 2026-08-06(목)도 같은 주
    weeks = dash.available_weeks()
    assert weeks[0] == "2026-08-03"
    # 2026-07-15(수)가 속한 주의 월요일은 2026-07-13
    assert "2026-07-13" in weeks


def test_week_range_returns_monday_to_sunday():
    assert dash.week_range("2026-08-03") == ("2026-08-03", "2026-08-09")


def test_range_summary_matches_monthly_summary_for_full_month(db):
    _seed_sample_data()
    range_result = dash.range_summary("2026-08-01", "2026-08-31")
    monthly_result = dash.monthly_summary("2026-08")
    assert range_result == monthly_result


def test_expense_by_major_category_range_for_single_week(db):
    _seed_sample_data()
    # 2026-08-03~09 주에는 8월 지출 3건(대신주유소/모임방A/이름모를가게)이 모두 포함됨
    rows = {r["major_category"]: r["amount"] for r in dash.expense_by_major_category_range("2026-08-03", "2026-08-09")}
    assert rows == {"변동비": 100000, "라이프스타일비": 6800, "미분류·확인필요": 5000}


def test_daily_expense_in_range(db):
    _seed_sample_data()
    daily = dash.daily_expense_in_range("2026-08-01", "2026-08-31")
    assert daily == {"2026-08-08": 100000, "2026-08-06": 6800, "2026-08-05": 5000}


def test_cumulative_summary_with_fixed_today(db):
    _seed_sample_data()
    summary = dash.cumulative_summary(today=date(2026, 8, 8))
    # 이번주(2026-08-03~08)와 이번달(2026-08-01~08) 모두 8월 지출 3건을 전부 포함
    assert summary["week_expense"] == 111800
    assert summary["month_expense"] == 111800
    # 올해(2026-01-01~08-08): 위 + 7월 맛집 2만
    assert summary["year_expense"] == 131800
