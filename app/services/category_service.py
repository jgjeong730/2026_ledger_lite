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


UNCATEGORIZED_LABEL = "미분류"


def category_enum_options() -> list[str]:
    """'대분류>소분류' 형태의 지출 카테고리 전체 목록 + 미분류.

    Claude에게 구조화된 출력(JSON Schema enum)으로 카테고리를 강제할 때 공용으로 쓴다
    (vision_service의 영수증 OCR+분류, classification_service의 가맹점명 분류).
    """
    options = [
        f"{major}>{minor['minor_category']}"
        for major, minors in list_expense_categories().items()
        for minor in minors
    ]
    options.append(UNCATEGORIZED_LABEL)
    return options


def parse_category_enum_value(value: str) -> tuple[str | None, str | None]:
    """category_enum_options()가 반환한 값 하나를 (대분류, 소분류)로 분해한다. 미분류/형식 불일치는 (None, None)."""
    if value and ">" in value:
        major, minor = value.split(">", 1)
        return major, minor
    return None, None
