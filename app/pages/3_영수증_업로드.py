from datetime import date, datetime

import streamlit as st

from app.db.connection import init_db
from app.services.capture_service import save_receipt_image
from app.services.category_service import list_expense_categories
from app.services.receipt_service import ingest_receipt_image_manual

st.set_page_config(page_title="영수증 업로드 - ledger-lite", page_icon="\U0001F9FE")
init_db()

st.title("\U0001F9FE 영수증 업로드")
st.caption(
    "실물 영수증 사진을 올려주세요. Claude Vision OCR 자동 인식은 3단계에서 연결되며, "
    "지금은 사진을 보며 직접 내용을 입력하는 방식입니다."
)

uploaded = st.file_uploader("영수증 이미지", type=["jpg", "jpeg", "png"])

if uploaded:
    st.image(uploaded, width=300)
    categories = list_expense_categories()

    with st.form("receipt_form"):
        col1, col2 = st.columns(2)
        with col1:
            merchant = st.text_input("거래처(가맹점명)")
            amount = st.number_input("금액(원)", min_value=0, step=100, value=0)
        with col2:
            txn_date = st.date_input("거래일", value=date.today())
            txn_time = st.time_input("거래시각", value=datetime.now().time().replace(microsecond=0))

        major = st.selectbox("대분류", list(categories.keys()))
        minor_options = categories[major]
        minor = st.selectbox("소분류", [m["minor_category"] for m in minor_options])
        memo = st.text_input("메모(선택)")
        submitted = st.form_submit_button("등록", type="primary")

    if submitted:
        if not merchant or amount <= 0:
            st.error("거래처와 금액을 입력해주세요.")
        else:
            image_path = save_receipt_image(uploaded.getvalue(), uploaded.name)
            category_id = next(m["id"] for m in minor_options if m["minor_category"] == minor)
            ingest_receipt_image_manual(
                image_path=image_path,
                merchant_name=merchant,
                amount=int(amount),
                txn_date=txn_date.isoformat(),
                txn_time=txn_time.strftime("%H:%M"),
                category_id=category_id,
                memo=memo or None,
            )
            st.success(f"등록 완료: {merchant} {amount:,.0f}원 ({major} > {minor})")
