"""대시보드용 집계 쿼리. 확정된 거래(receipts)를 현재 유효한 분류(classifications.is_current=1)
기준으로 집계한다. 카카오페이 '받았어요'(flow_direction='inflow')는 지출 합계에서 자동으로
빠진다 - 정산 환급을 지출로 이중 계산하지 않기 위함 (main.py의 summary_counts와 동일한 정의).
"""

from datetime import date, timedelta

from app.db import dialect
from app.db.connection import get_connection

# categories 시드 순서와 동일 - 대시보드 차트에서 항상 이 순서로 표시/배색한다.
MAJOR_CATEGORY_ORDER = ["고정비", "변동비", "라이프스타일비", "가족·경조사비", "비정기 대형지출"]


def available_months() -> list[str]:
    """거래가 존재하는 'YYYY-MM' 목록, 최신순."""
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT {dialect.year_month_expr('transaction_date')} AS month
            FROM receipts
            ORDER BY month DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return [r["month"] for r in rows]


def monthly_summary(month: str) -> dict:
    ym = dialect.year_month_expr("transaction_date")
    conn = get_connection()
    try:
        expense = conn.execute(
            f"""
            SELECT COALESCE(SUM(amount), 0) AS total FROM receipts
            WHERE entry_type = 'expense' AND flow_direction = 'outflow'
              AND {ym} = ?
            """,
            (month,),
        ).fetchone()["total"]
        income = conn.execute(
            f"""
            SELECT COALESCE(SUM(amount), 0) AS total FROM receipts
            WHERE entry_type = 'income'
              AND {ym} = ?
            """,
            (month,),
        ).fetchone()["total"]
        needs_review = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM receipts
            WHERE review_status = 'needs_review'
              AND {ym} = ?
            """,
            (month,),
        ).fetchone()["n"]
        receipt_count = conn.execute(
            f"SELECT COUNT(*) AS n FROM receipts WHERE {ym} = ?",
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
    ym = dialect.year_month_expr("r.transaction_date")
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT c.major_category AS major_category, SUM(r.amount) AS amount
            FROM receipts r
            JOIN classifications cl ON cl.receipt_id = r.id AND cl.is_current = 1
            JOIN categories c ON c.id = cl.category_id
            WHERE r.entry_type = 'expense' AND r.flow_direction = 'outflow'
              AND {ym} = ?
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
        query = f"""
            SELECT c.major_category AS major_category, c.minor_category AS minor_category,
                   SUM(r.amount) AS amount
            FROM receipts r
            JOIN classifications cl ON cl.receipt_id = r.id AND cl.is_current = 1
            JOIN categories c ON c.id = cl.category_id
            WHERE r.entry_type = 'expense' AND r.flow_direction = 'outflow'
              AND {dialect.year_month_expr('r.transaction_date')} = ?
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
            f"""
            SELECT {dialect.year_month_expr('transaction_date')} AS month,
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


def available_weeks() -> list[str]:
    """거래가 존재하는 주의 시작일(월요일, 'YYYY-MM-DD') 목록, 최신순."""
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT {dialect.week_start_expr('transaction_date')} AS week_start
            FROM receipts
            ORDER BY week_start DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return [r["week_start"] for r in rows]


def week_range(week_start: str) -> tuple[str, str]:
    """주 시작일(월요일)로부터 (시작일, 종료일=일요일) 튜플을 반환한다."""
    end = date.fromisoformat(week_start) + timedelta(days=6)
    return week_start, end.isoformat()


def range_summary(start: str, end: str) -> dict:
    """월간 monthly_summary()의 임의 기간(YYYY-MM-DD~YYYY-MM-DD) 버전. 주간 보기에서 사용."""
    conn = get_connection()
    try:
        expense = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total FROM receipts
            WHERE entry_type = 'expense' AND flow_direction = 'outflow'
              AND transaction_date BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchone()["total"]
        income = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM receipts WHERE entry_type = 'income' AND transaction_date BETWEEN ? AND ?",
            (start, end),
        ).fetchone()["total"]
        needs_review = conn.execute(
            "SELECT COUNT(*) AS n FROM receipts WHERE review_status = 'needs_review' AND transaction_date BETWEEN ? AND ?",
            (start, end),
        ).fetchone()["n"]
        receipt_count = conn.execute(
            "SELECT COUNT(*) AS n FROM receipts WHERE transaction_date BETWEEN ? AND ?", (start, end)
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


def expense_by_major_category_range(
    start: str, end: str, exclude_majors: list[str] | None = None
) -> list[dict]:
    """expense_by_major_category()의 임의 기간 버전. exclude_majors에 담긴 대분류는 제외한다
    (예: '비정기 대형지출' 같은 일회성 큰 지출을 트렌드 분석에서 빼고 싶을 때)."""
    conn = get_connection()
    try:
        query = """
            SELECT c.major_category AS major_category, SUM(r.amount) AS amount
            FROM receipts r
            JOIN classifications cl ON cl.receipt_id = r.id AND cl.is_current = 1
            JOIN categories c ON c.id = cl.category_id
            WHERE r.entry_type = 'expense' AND r.flow_direction = 'outflow'
              AND r.transaction_date BETWEEN ? AND ?
        """
        params: list = [start, end]
        if exclude_majors:
            query += f" AND c.major_category NOT IN ({','.join(['?'] * len(exclude_majors))})"
            params.extend(exclude_majors)
        query += " GROUP BY c.major_category ORDER BY amount DESC"
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def expense_by_category_range(
    start: str, end: str, limit: int | None = None, exclude_majors: list[str] | None = None
) -> list[dict]:
    """expense_by_category()의 임의 기간 버전. exclude_majors는 expense_by_major_category_range()와 동일."""
    conn = get_connection()
    try:
        query = """
            SELECT c.major_category AS major_category, c.minor_category AS minor_category,
                   SUM(r.amount) AS amount
            FROM receipts r
            JOIN classifications cl ON cl.receipt_id = r.id AND cl.is_current = 1
            JOIN categories c ON c.id = cl.category_id
            WHERE r.entry_type = 'expense' AND r.flow_direction = 'outflow'
              AND r.transaction_date BETWEEN ? AND ?
        """
        params: list = [start, end]
        if exclude_majors:
            query += f" AND c.major_category NOT IN ({','.join(['?'] * len(exclude_majors))})"
            params.extend(exclude_majors)
        query += " GROUP BY c.major_category, c.minor_category ORDER BY amount DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def daily_expense_in_range(start: str, end: str) -> dict[str, int]:
    """기간 내 날짜별 지출 합계 {'YYYY-MM-DD': amount}. 주간 막대 차트/캘린더 뷰 공용."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT transaction_date AS day, SUM(amount) AS amount
            FROM receipts
            WHERE entry_type = 'expense' AND flow_direction = 'outflow'
              AND transaction_date BETWEEN ? AND ?
            GROUP BY transaction_date
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()
    return {r["day"]: r["amount"] for r in rows}


def cumulative_summary(today: date | None = None) -> dict:
    """오늘 기준 이번 주(월요일부터)/이번 달(1일부터)/올해(1/1부터) 누적 지출·수입·순증감."""
    today = today or date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    month_start = today.replace(day=1).isoformat()
    year_start = today.replace(month=1, day=1).isoformat()
    today_str = today.isoformat()

    conn = get_connection()
    try:

        def _sum(entry_type: str, start: str) -> int:
            flow_clause = "AND flow_direction = 'outflow'" if entry_type == "expense" else ""
            return conn.execute(
                f"""
                SELECT COALESCE(SUM(amount), 0) AS total FROM receipts
                WHERE entry_type = ? {flow_clause}
                  AND transaction_date BETWEEN ? AND ?
                """,
                (entry_type, start, today_str),
            ).fetchone()["total"]

        result: dict = {}
        for label, start in (("week", week_start), ("month", month_start), ("year", year_start)):
            expense = _sum("expense", start)
            income = _sum("income", start)
            result[f"{label}_expense"] = expense
            result[f"{label}_income"] = income
            result[f"{label}_net"] = income - expense
    finally:
        conn.close()

    return result


def monthly_trend_fixed(months_back: int = 6, today: date | None = None) -> list[dict]:
    """오늘이 속한 달까지 최근 N개월을 고정 캘린더 윈도우로 반환한다 (데이터 없는 달은 0원).
    monthly_trend()와 달리 "데이터가 있는 달만"이 아니라 항상 정확히 months_back개를 반환한다."""
    today = today or date.today()
    months = []
    y, m = today.year, today.month
    for i in range(months_back - 1, -1, -1):
        mm = m - i
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        months.append(f"{yy:04d}-{mm:02d}")

    ym = dialect.year_month_expr("transaction_date")
    placeholders = ",".join(["?"] * len(months))
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT {ym} AS month,
                   SUM(CASE WHEN entry_type = 'expense' AND flow_direction = 'outflow' THEN amount ELSE 0 END) AS expense,
                   SUM(CASE WHEN entry_type = 'income' THEN amount ELSE 0 END) AS income
            FROM receipts
            WHERE {ym} IN ({placeholders})
            GROUP BY month
            """,
            months,
        ).fetchall()
    finally:
        conn.close()

    by_month = {r["month"]: r for r in rows}
    return [
        {
            "month": m,
            "expense": by_month[m]["expense"] if m in by_month else 0,
            "income": by_month[m]["income"] if m in by_month else 0,
        }
        for m in months
    ]


def weekly_trend_fixed(weeks_back: int = 12, today: date | None = None) -> list[dict]:
    """오늘이 속한 주(월요일)까지 최근 N주를 고정 윈도우로 반환한다 (데이터 없는 주는 0원)."""
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    week_starts = [(this_monday - timedelta(weeks=i)).isoformat() for i in range(weeks_back - 1, -1, -1)]

    week_expr = dialect.week_start_expr("transaction_date")
    placeholders = ",".join(["?"] * len(week_starts))
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT {week_expr} AS week_start,
                   SUM(CASE WHEN entry_type = 'expense' AND flow_direction = 'outflow' THEN amount ELSE 0 END) AS expense,
                   SUM(CASE WHEN entry_type = 'income' THEN amount ELSE 0 END) AS income
            FROM receipts
            WHERE {week_expr} IN ({placeholders})
            GROUP BY week_start
            """,
            week_starts,
        ).fetchall()
    finally:
        conn.close()

    by_week = {r["week_start"]: r for r in rows}
    return [
        {
            "week_start": w,
            "expense": by_week[w]["expense"] if w in by_week else 0,
            "income": by_week[w]["income"] if w in by_week else 0,
        }
        for w in week_starts
    ]


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
