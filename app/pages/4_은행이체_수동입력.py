import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if p.name == "app").parent))

import streamlit as st

from app.auth import require_login
from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.services.category_service import list_expense_categories, list_income_categories
from app.services.receipt_service import create_manual_entry
from app.theme import apply_theme

st.set_page_config(page_title="은행이체 수동입력 - ledger-lite", page_icon="\U0001F3E6")
require_login()
apply_theme()
init_db()
seed_categories()

st.title("\U0001F3E6 은행이체 / 수동입력")
st.caption(
    "구독료·통신비·보험료·연금 등 은행 계좌이체/출금은 적요만으로 자동분류가 어려워 직접 입력합니다. "
    "연금 인출액은 출처 분석 없이 '연금인출유입' 금액만 기록하세요. "
    "여러 건을 아래에 계속 추가한 뒤 맨 아래 '전체 등록'으로 한 번에 저장하세요."
)

entry_type_label = st.radio("구분", ["지출", "수입"], horizontal=True)

expense_categories = list_expense_categories()
income_categories = list_income_categories()

if "manual_row_ids" not in st.session_state:
    st.session_state.manual_row_ids = [str(uuid4())]


def _add_row():
    st.session_state.manual_row_ids.append(str(uuid4()))


def _remove_row(rid):
    st.session_state.manual_row_ids.remove(rid)


# 대분류/소분류는 폼 없이 일반 위젯으로 둔다 - st.form 안의 위젯은 제출 전까지 재실행을 트리거하지
# 않아서, 폼 안에 있으면 대분류를 바꿔도 소분류 목록이 즉시 갱신되지 않는다.
rows_data = []

for idx, rid in enumerate(st.session_state.manual_row_ids):
    with st.container(border=True):
        header_col, remove_col = st.columns([8, 1])
        with header_col:
            st.markdown(f"**#{idx + 1}**")
        with remove_col:
            if len(st.session_state.manual_row_ids) > 1:
                st.button("삭제", key=f"remove_{rid}", on_click=_remove_row, args=(rid,))

        col_major, col_minor, col_date = st.columns(3)
        major_val = None
        minor_val = None
        with col_major:
            if entry_type_label == "지출":
                major_val = st.selectbox("대분류", list(expense_categories.keys()), key=f"major_{rid}")
            else:
                minor_val = st.selectbox(
                    "수입 종류", [c["minor_category"] for c in income_categories], key=f"minor_{rid}"
                )
        with col_minor:
            if entry_type_label == "지출":
                minor_options = expense_categories[major_val]
                minor_val = st.selectbox(
                    "소분류", [m["minor_category"] for m in minor_options], key=f"minor_{rid}"
                )
        with col_date:
            txn_date = st.date_input("거래일", value=date.today(), key=f"date_{rid}")

        col_merchant, col_amount, col_memo = st.columns(3)
        with col_merchant:
            merchant = st.text_input("적요 / 거래처 (예: 메리츠07-092)", key=f"merchant_{rid}")
        with col_amount:
            amount = st.number_input("금액(원)", min_value=0, step=1000, value=0, key=f"amount_{rid}")
        with col_memo:
            memo = st.text_input("메모(선택)", key=f"memo_{rid}")

    rows_data.append(
        {
            "merchant": merchant,
            "amount": amount,
            "txn_date": txn_date,
            "memo": memo,
            "major": major_val,
            "minor": minor_val,
        }
    )

st.button("+ 행 추가", on_click=_add_row)

if st.button("전체 등록", type="primary"):
    inserted = 0
    for row in rows_data:
        if row["amount"] <= 0:
            continue
        if entry_type_label == "지출":
            minor_options = expense_categories[row["major"]]
            category_id = next(m["id"] for m in minor_options if m["minor_category"] == row["minor"])
            create_manual_entry(
                entry_type="expense",
                merchant_name=row["merchant"] or None,
                amount=int(row["amount"]),
                transaction_date=row["txn_date"].isoformat(),
                category_id=category_id,
                memo=row["memo"] or None,
            )
        else:
            category_id = next(c["id"] for c in income_categories if c["minor_category"] == row["minor"])
            create_manual_entry(
                entry_type="income",
                merchant_name=row["merchant"] or None,
                amount=int(row["amount"]),
                transaction_date=row["txn_date"].isoformat(),
                category_id=category_id,
                memo=row["memo"] or None,
            )
        inserted += 1

    if inserted == 0:
        st.error("금액이 입력된 행이 없습니다.")
    else:
        st.success(f"{inserted}건 등록 완료")
        for key in list(st.session_state.keys()):
            if key.startswith(("major_", "minor_", "date_", "merchant_", "amount_", "memo_", "remove_")):
                del st.session_state[key]
        st.session_state.manual_row_ids = [str(uuid4())]
        st.rerun()
