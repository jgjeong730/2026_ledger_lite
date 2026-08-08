"""대시보드용 집계 쿼리. 확정된 거래(receipts)를 현재 유효한 분류(classifications.is_current=1)
기준으로 집계한다. 카카오페이 '받았어요'(flow_direction='inflow')는 지출 합계에서 자동으로
빠진다 - 정산 환급을 지출로 이중 계산하지 않기 위함 (main.py의 summary_counts와 동일한 정의).
"""

from app.db.connection import get_connection

# categories 시드 순서와 동일 - 대시보드 차트에서 항상 이 순서로 표시/배색한다.
MAJOR_CATEGORY_ORDER = ["고정비", "변동비", "라이프스타일비", "가족·경조사비", "비정기 대형지출"]


def available_months() -> list[str]:
    """거래가 존재하는 'YYYY-MM' 목록, 최신순."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT strftime('%Y-%m', transaction_date) AS month
            FROM receipts
            ORDER BY month DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return [r["month"] for r in rows]


def monthly_summary(month: str) -> dict:
    conn = get_connection()
    try:
        expense = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total FROM receipts
            WHERE entry_type = 'expense' AND flow_direction = 'outflow'
              AND strftime('%Y-%m', transaction_date) = ?
            """,
            (month,),
        ).fetchone()["total"]
        income = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total FROM receipts
            WHERE entry_type = 'income'
              AND strftime('%Y-%m', transaction_date) = ?
            """,
            (month,),
        ).fetchone()["total"]
        needs_review = conn.execute(
            """
            SELECT COUNT(*) AS n FROM receipts
            WHERE review_status = 'needs_review'
              AND strftime('%Y-%m', transaction_date) = ?
            """,
            (month,),
        ).fetchone()["n"]
        receipt_count = conn.execute(
            "SELECT COUNT(*) AS n FROM receipts WHERE strftime('%Y-%m', transaction_date) = ?",
            (month,),
        ).fetchone()["n"]
    finally:
        conn.close()
    return {
        "expense": expense,
        "income": income,
        "net": income - expense,
        "needs_review": needs_review,
        "receipt_count": receipt_count,
    }


def expense_by_major_category(month: str) -> list[dict]:
    """해당 월 대분류별 지출 합계, 금액 내림차순. 지출이 없던 대분류는 포함하지 않는다."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT c.major_category AS major_category, SUM(r.amount) AS amount
            FROM receipts r
            JOIN classifications cl ON cl.receipt_id = r.id AND cl.is_current = 1
            JOIN categories c ON c.id = cl.category_id
            WHERE r.entry_type = 'expense' AND r.flow_direction = 'outflow'
              AND strftime('%Y-%m', r.transaction_date) = ?
            GROUP BY c.major_category
            ORDER BY amount DESC
            """,
            (month,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def expense_by_category(month: str, limit: int | None = None) -> list[dict]:
    """해당 월 (대분류, 소분류)별 지출 합계, 금액 내림차순. '미분류·확인필요'도 포함해
    전체 지출과 합계가 항상 일치하도록 한다 (사용자가 확인이 얼마나 밀려있는지도 한눈에 보이게)."""
    conn = get_connection()
    try:
        query = """
            SELECT c.major_category AS major_category, c.minor_category AS minor_category,
                   SUM(r.amount) AS amount
            FROM receipts r
            JOIN classifications cl ON cl.receipt_id = r.id AND cl.is_current = 1
            JOIN categories c ON c.id = cl.category_id
            WHERE r.entry_type = 'expense' AND r.flow_direction = 'outflow'
              AND strftime('%Y-%m', r.transaction_date) = ?
            GROUP BY c.major_category, c.minor_category
            ORDER BY amount DESC
        """
        params: list = [month]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def monthly_trend(months_back: int = 6) -> list[dict]:
    """데이터가 있는 최근 N개월의 지출/수입 합계를 오래된 순으로 반환 (추이 차트용)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT strftime('%Y-%m', transaction_date) AS month,
                   SUM(CASE WHEN entry_type = 'expense' AND flow_direction = 'outflow' THEN amount ELSE 0 END) AS expense,
                   SUM(CASE WHEN entry_type = 'income' THEN amount ELSE 0 END) AS income
            FROM receipts
            GROUP BY month
            ORDER BY month DESC
            LIMIT ?
            """,
            (months_back,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in reversed(rows)]


def build_monthly_report_text(month: str) -> str:
    """카카오톡 '나에게 보내기'로 보낼 월간 리포트 텍스트 (6단계)."""
    summary = monthly_summary(month)
    majors = expense_by_major_category(month)

    lines = [
        f"\U0001F4CA ledger-lite {month} 리포트",
        "",
        f"지출 {summary['expense']:,}원 / 수입 {summary['income']:,}원",
        f"순증감 {summary['net']:+,}원",
    ]
    if summary["needs_review"] > 0:
        lines.append(f"⚠️ 확인 필요 {summary['needs_review']}건")

    if majors:
        lines.append("")
        lines.append("[대분류별 지출]")
        for row in majors:
            lines.append(f"- {row['major_category']}: {row['amount']:,}원")

    return "\n".join(lines)
