import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if p.name == "app").parent))

from datetime import date

import pandas as pd
import streamlit as st

from app.auth import require_login
from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.services.category_service import list_expense_categories, list_income_categories
from app.services.dashboard_service import available_months
from app.services.receipt_service import delete_receipt, list_receipts, reclassify_and_learn, update_receipt
from app.theme import apply_theme

st.set_page_config(page_title="거래내역 - ledger-lite", page_icon="\U0001F4CB", layout="wide")
require_login()
apply_theme()
init_db()
seed_categories()

st.title("\U0001F4CB 거래내역 확인 / 재분류")

available_month_values = available_months()
year_options = sorted({int(month[:4]) for month in available_month_values} | {date.today().year})

col1, col2, col3, col4, col5 = st.columns([1.2, 1.2, 1.2, 1.4, 1.4])
with col1:
    type_label = st.selectbox("구분", ["전체", "지출", "수입"])
with col2:
    year_label = st.selectbox("연도", ["전체"] + year_options)
with col3:
    month_label = st.selectbox("월", ["전체"] + list(range(1, 13)), format_func=lambda m: "전체" if m == "전체" else f"{m}월")
with col4:
    expense_categories = list_expense_categories()
    major_label = st.multiselect("대분류", list(expense_categories.keys()))
with col5:
    if not major_label:
        minor_options = list(
            dict.fromkeys(
                minor["minor_category"]
                for minors in expense_categories.values()
                for minor in minors
            )
        )
    else:
        minor_options = list(
            dict.fromkeys(
                minor["minor_category"]
                for major in major_label
                for minor in expense_categories[major]
            )
        )
    minor_label = st.multiselect("소분류", minor_options, key=f"transaction_minor_{'-'.join(major_label)}")

entry_type = {"지출": "expense", "수입": "income"}.get(type_label)
year = None if year_label == "전체" else year_label
month_number = None if month_label == "전체" else month_label
major_category = major_label or None
minor_category = minor_label or None

receipts = list_receipts(
    entry_type=entry_type,
    year=year,
    month_number=month_number,
    major_category=major_category,
    minor_category=minor_category,
)

if not receipts:
    st.info("표시할 거래가 없습니다.")
else:
    st.caption(f"{len(receipts)}건")

    table_rows = [
        {
            "날짜": r["transaction_date"],
            "구분": "지출" if r["entry_type"] == "expense" else "수입",
            "거래처": r["merchant_name"] or "-",
            "금액": r["amount"],
            "카테고리": (r["major_category"] or "미분류")
            + (f" > {r['minor_category']}" if r["minor_category"] else ""),
            "상태": "확인필요" if r["review_status"] == "needs_review" else "확인완료",
        }
        for r in receipts
    ]
    df = pd.DataFrame(table_rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("\U0001F4CA 카테고리별 합계")
    summary_df = (
        df.groupby(["구분", "카테고리"], as_index=False)["금액"]
        .sum()
        .sort_values(["구분", "금액"], ascending=[True, False])
        .reset_index(drop=True)
    )
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    st.divider()
    st.caption("아래에서 거래를 펼쳐 카테고리를 수정하면 같은 가맹점의 다음 문자에 자동 반영됩니다.")

    expense_categories = list_expense_categories()
    income_categories = list_income_categories()

    for r in receipts:
        direction_icon = "\U0001F53B" if r["flow_direction"] == "outflow" else "\U0001F53A"
        category_label = (r["major_category"] or "미분류") + (
            f" > {r['minor_category']}" if r["minor_category"] else ""
        )
        review_mark = " ⚠️확인필요" if r["review_status"] == "needs_review" else ""
        title = (
            f"{direction_icon} {r['transaction_date']} · {r['merchant_name'] or '(거래처 없음)'} · "
            f"{r['amount']:,}원 · {category_label}{review_mark}"
        )
        with st.expander(title):
            st.write(
                f"소스: `{r['source_type']}` · 분류방식: `{r['classified_by'] or '-'}` · 메모: {r['memo'] or '-'}"
            )

            if r["entry_type"] == "expense":
                major_options = list(expense_categories.keys())
                current_major = r["major_category"] if r["major_category"] in major_options else major_options[0]
                new_major = st.selectbox(
                    "대분류", major_options, index=major_options.index(current_major), key=f"major_{r['id']}"
                )
                minor_opts = expense_categories[new_major]
                minor_names = [m["minor_category"] for m in minor_opts]
                default_idx = minor_names.index(r["minor_category"]) if r["minor_category"] in minor_names else 0
                new_minor = st.selectbox("소분류", minor_names, index=default_idx, key=f"minor_{r['id']}")
                new_category_id = next(m["id"] for m in minor_opts if m["minor_category"] == new_minor)
            else:
                minor_names = [c["minor_category"] for c in income_categories]
                default_idx = minor_names.index(r["minor_category"]) if r["minor_category"] in minor_names else 0
                new_minor = st.selectbox("수입 종류", minor_names, index=default_idx, key=f"minor_{r['id']}")
                new_category_id = next(c["id"] for c in income_categories if c["minor_category"] == new_minor)

            if st.button("이 분류로 확정", key=f"confirm_{r['id']}"):
                reclassify_and_learn(
                    receipt_id=r["id"],
                    category_id=new_category_id,
                    merchant_name=r["merchant_name"],
                    source_type=r["source_type"],
                )
                st.success("반영되었습니다.")
                st.rerun()

            st.divider()
            st.caption("거래처·금액·날짜·메모가 잘못 들어왔으면 여기서 직접 고치세요.")

            edit_col1, edit_col2 = st.columns(2)
            with edit_col1:
                new_merchant = st.text_input(
                    "거래처", value=r["merchant_name"] or "", key=f"merchant_{r['id']}"
                )
                new_amount = st.number_input(
                    "금액", min_value=0, step=100, value=r["amount"], key=f"amount_{r['id']}"
                )
            with edit_col2:
                new_date = st.date_input(
                    "날짜", value=date.fromisoformat(r["transaction_date"]), key=f"date_{r['id']}"
                )
                new_memo = st.text_input("메모", value=r["memo"] or "", key=f"memo_{r['id']}")

            new_flow_direction = None
            if r["source_type"] == "kakaopay":
                # 카카오페이는 방향 표시 없는 형식("상대방 금액 월/일")이면 항상 보낸 것으로
                # 등록되므로, 실제로는 받은 돈이었을 때 여기서 바로잡을 수 있어야 한다.
                direction_label = st.radio(
                    "방향",
                    ["보낸 것", "받은 것"],
                    index=0 if r["flow_direction"] == "outflow" else 1,
                    key=f"direction_{r['id']}",
                    horizontal=True,
                )
                new_flow_direction = "outflow" if direction_label == "보낸 것" else "inflow"

            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("수정 저장", key=f"save_{r['id']}"):
                    update_receipt(
                        r["id"],
                        merchant_name=new_merchant.strip() or None,
                        amount=int(new_amount),
                        transaction_date=new_date.isoformat(),
                        memo=new_memo.strip() or None,
                        flow_direction=new_flow_direction,
                    )
                    st.success("수정되었습니다.")
                    st.rerun()
            with btn_col2:
                delete_pending_key = f"delete_pending_{r['id']}"
                if not st.session_state.get(delete_pending_key):
                    if st.button("\U0001F5D1️ 삭제", key=f"delete_{r['id']}"):
                        st.session_state[delete_pending_key] = True
                        st.rerun()
                else:
                    st.warning("정말 삭제할까요? 되돌릴 수 없습니다.")
                    confirm_col1, confirm_col2 = st.columns(2)
                    with confirm_col1:
                        if st.button("삭제 확정", key=f"delete_confirm_{r['id']}", type="primary"):
                            delete_receipt(r["id"])
                            st.session_state.pop(delete_pending_key, None)
                            st.success("삭제되었습니다.")
                            st.rerun()
                    with confirm_col2:
                        if st.button("취소", key=f"delete_cancel_{r['id']}"):
                            st.session_state.pop(delete_pending_key, None)
                            st.rerun()
