import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if p.name == "app").parent))

import streamlit as st

from app.auth import require_login
from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.services.category_service import list_expense_categories, list_income_categories
from app.services.receipt_service import create_manual_entry

st.set_page_config(page_title="은행이체 수동입력 - ledger-lite", page_icon="\U0001F3E6")
require_login()
init_db()
seed_categories()

st.title("\U0001F3E6 은행이체 / 수동입력")
st.caption(
    "구독료·통신비·보험료·연금 등 은행 계좌이체/출금은 적요만으로 자동분류가 어려워 직접 입력합니다. "
    "연금 인출액은 출처 분석 없이 '연금인출유입' 금액만 기록하세요."
)

entry_type_label = st.radio("구분", ["지출", "수입"], horizontal=True)

expense_categories = list_expense_categories()
income_categories = list_income_categories()

# 대분류는 폼 밖에 둔다 - st.form 안의 위젯은 "등록" 제출 전까지 재실행을 트리거하지 않아서,
# 폼 안에 있으면 대분류를 바꿔도 소분류 목록이 즉시 갱신되지 않는다(항상 첫 대분류 기준으로 보임).
major = None
if entry_type_label == "지출":
    major = st.selectbox("대분류", list(expense_categories.keys()))

with st.form("manual_entry_form"):
    col1, col2 = st.columns(2)
    with col1:
        merchant = st.text_input("적요 / 거래처 (예: 메리츠07-092)")
        amount = st.number_input("금액(원)", min_value=0, step=1000, value=0)
    with col2:
        txn_date = st.date_input("거래일", value=date.today())

    if entry_type_label == "지출":
        minor_options = expense_categories[major]
        minor = st.selectbox("소분류", [m["minor_category"] for m in minor_options])
    else:
        minor = st.selectbox("수입 종류", [c["minor_category"] for c in income_categories])

    memo = st.text_input("메모(선택)")
    submitted = st.form_submit_button("등록", type="primary")

if submitted:
    if amount <= 0:
        st.error("금액을 입력해주세요.")
    elif entry_type_label == "지출":
        category_id = next(m["id"] for m in minor_options if m["minor_category"] == minor)
        create_manual_entry(
            entry_type="expense",
            merchant_name=merchant or None,
            amount=int(amount),
            transaction_date=txn_date.isoformat(),
            category_id=category_id,
            memo=memo or None,
        )
        st.success(f"지출 등록 완료: {merchant or '(적요 없음)'} {amount:,.0f}원 ({major} > {minor})")
    else:
        category_id = next(c["id"] for c in income_categories if c["minor_category"] == minor)
        create_manual_entry(
            entry_type="income",
            merchant_name=merchant or None,
            amount=int(amount),
            transaction_date=txn_date.isoformat(),
            category_id=category_id,
            memo=memo or None,
        )
        st.success(f"수입 등록 완료: {amount:,.0f}원 ({minor})")
