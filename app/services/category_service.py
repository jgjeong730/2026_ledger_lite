"""categories 테이블 조회 헬퍼. UI 드롭다운과 기본 분류 로직에서 공용으로 사용."""

from app.db.connection import get_connection


def list_expense_categories() -> dict[str, list[dict]]:
    """대분류 -> [{id, minor_category}, ...] (sort_order 순). 시스템 카테고리는 제외."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, major_category, minor_category
            FROM categories
            WHERE entry_type = 'expense' AND is_system = 0 AND is_active = 1
            ORDER BY sort_order
            """
        ).fetchall()
    finally:
        conn.close()

    majors: dict[str, list[dict]] = {}
    for row in rows:
        majors.setdefault(row["major_category"], []).append(
            {"id": row["id"], "minor_category": row["minor_category"]}
        )
    return majors


def list_income_categories() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, major_category, minor_category
            FROM categories
            WHERE entry_type = 'income' AND is_active = 1
            ORDER BY sort_order
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_category_id(entry_type: str, major_category: str, minor_category: str = "") -> int | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id FROM categories
            WHERE entry_type = ? AND major_category = ? AND minor_category = ?
            """,
            (entry_type, major_category, minor_category),
        ).fetchone()
    finally:
        conn.close()
    return row["id"] if row else None


def get_uncategorized_category_id() -> int:
    cat_id = get_category_id("expense", "미분류·확인필요", "")
    if cat_id is None:
        raise RuntimeError(
            "시스템 카테고리 '미분류·확인필요'가 없습니다. seed_categories()를 먼저 실행하세요."
        )
    return cat_id


def get_kakaopay_default_category_id() -> int:
    cat_id = get_category_id("expense", "라이프스타일비", "소셜/네트워킹")
    if cat_id is None:
        raise RuntimeError("카테고리 '라이프스타일비 > 소셜/네트워킹'이 없습니다.")
    return cat_id
