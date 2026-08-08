import pandas as pd
import streamlit as st

from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.services.category_service import list_expense_categories, list_income_categories
from app.services.receipt_service import list_receipts, reclassify_and_learn

st.set_page_config(page_title="거래내역 - ledger-lite", page_icon="\U0001F4CB", layout="wide")
init_db()
seed_categories()

st.title("\U0001F4CB 거래내역 확인 / 재분류")

col1, col2 = st.columns(2)
with col1:
    status_label = st.selectbox("상태", ["전체", "확인 필요", "확인 완료"])
with col2:
    type_label = st.selectbox("구분", ["전체", "지출", "수입"])

review_status = {"확인 필요": "needs_review", "확인 완료": "confirmed"}.get(status_label)
entry_type = {"지출": "expense", "수입": "income"}.get(type_label)

receipts = list_receipts(review_status=review_status, entry_type=entry_type)

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
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

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
