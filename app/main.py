"""ledger-lite Streamlit 진입점.

1단계(프로젝트 구조 & DB 스키마) 시점에는 DB 초기화/카테고리 시드 상태를 확인하는
최소 화면만 제공한다. 영수증 업로드/수동 입력 UI는 2단계에서 구현한다.
"""

import streamlit as st

from app.db.connection import get_connection, init_db
from app.db.seed_categories import seed_categories

st.set_page_config(page_title="ledger-lite", page_icon="\U0001F4B0")

init_db()
seed_categories()

st.title("ledger-lite")
st.caption("은퇴 후 생활비 소비 관리 - 1단계: 프로젝트 구조 & DB 스키마")

conn = get_connection()
try:
    tables = [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    st.subheader("DB 테이블")
    st.write(tables)

    st.subheader("카테고리 시드 현황")
    rows = conn.execute(
        """
        SELECT entry_type, major_category, COUNT(*) AS cnt
        FROM categories
        GROUP BY entry_type, major_category
        ORDER BY entry_type, MIN(sort_order)
        """
    ).fetchall()
    st.table([dict(r) for r in rows])
finally:
    conn.close()

st.success("DB 초기화 및 카테고리 시드 완료. 2단계(영수증 업로드 + 수동 입력)에서 이어집니다.")
