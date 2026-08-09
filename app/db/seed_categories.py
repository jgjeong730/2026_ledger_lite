"""지출 5대분류/소분류 + 수입 2종 + 시스템 상태값을 categories 테이블에 채운다.

docs/PROJECT_BRIEF.md 5절(계정과목 체계)의 최종 확정안을 그대로 반영.
여러 번 실행해도 안전하다 (categories.UNIQUE(entry_type, major_category, minor_category)에 의존).
"""

from app.db.connection import get_connection, init_db

# (entry_type, major_category, minor_category, is_system, sort_order)
CATEGORY_SEED = [
    # 고정비
    ("expense", "고정비", "관리비·공과금", 0, 10),
    ("expense", "고정비", "통신비", 0, 11),
    ("expense", "고정비", "보험료", 0, 12),
    ("expense", "고정비", "연금성 지출", 0, 13),
    ("expense", "고정비", "구독서비스", 0, 14),
    # 변동비
    ("expense", "변동비", "식비(외식·배달)", 0, 20),
    ("expense", "변동비", "마트·생필품", 0, 21),
    ("expense", "변동비", "교통·주유", 0, 22),
    ("expense", "변동비", "의료·건강", 0, 23),
    ("expense", "변동비", "미용", 0, 24),
    ("expense", "변동비", "기타", 0, 25),
    # 라이프스타일비
    ("expense", "라이프스타일비", "테니스", 0, 30),
    ("expense", "라이프스타일비", "러닝·트레킹", 0, 31),
    ("expense", "라이프스타일비", "취미·여가", 0, 32),
    ("expense", "라이프스타일비", "도서·자기계발", 0, 33),
    # 카카오페이 송금(1/N 정산) 기본 배정 카테고리 - source_type='kakaopay'는 이 카테고리로 고정 배정
    ("expense", "라이프스타일비", "소셜/네트워킹", 0, 34),
    # 가족·경조사비
    ("expense", "가족·경조사비", "가족모임·외식", 0, 40),
    ("expense", "가족·경조사비", "경조사(축의금·부의금)", 0, 41),
    ("expense", "가족·경조사비", "자녀지원", 0, 42),
    ("expense", "가족·경조사비", "부모님지원", 0, 43),
    # 비정기 대형지출
    ("expense", "비정기 대형지출", "가전·전자기기", 0, 50),
    ("expense", "비정기 대형지출", "여행", 0, 51),
    ("expense", "비정기 대형지출", "고액의료비", 0, 52),
    # 시스템 상태값 (신뢰도 낮은 항목의 기본 상태 - 사용자가 고를 수 있는 정상 카테고리가 아님)
    # minor_category는 ''(빈 문자열)로 둔다: SQLite UNIQUE 제약은 NULL끼리 서로 다르게 취급해
    # NULL을 쓰면 재시드 시마다 중복 삽입되므로 사용하지 않는다.
    ("expense", "미분류·확인필요", "", 1, 90),
    # 수입 (연금/투자 분석 없이 금액만 단순 기록)
    ("income", "수입", "연금인출유입", 0, 100),
    ("income", "수입", "기타수입", 0, 101),
    ("income", "수입", "급여", 0, 102),
    ("income", "수입", "아르바이트", 0, 103),
    ("income", "수입", "실업급여", 0, 104),
]


def seed_categories() -> int:
    """카테고리 시드를 삽입한다. 새로 삽입된 행 수를 반환한다."""
    conn = get_connection()
    try:
        cur = conn.executemany(
            """
            INSERT OR IGNORE INTO categories
                (entry_type, major_category, minor_category, is_system, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            CATEGORY_SEED,
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    inserted = seed_categories()
    print(f"categories 시드 완료 (신규 삽입 {inserted}건, 총 정의 {len(CATEGORY_SEED)}건)")
