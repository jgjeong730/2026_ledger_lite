import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if p.name == "app").parent))

import streamlit as st

from app.auth import require_login
from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.services.capture_service import save_receipt_image
from app.services.category_service import list_expense_categories
from app.services.receipt_service import ingest_receipt_image_manual, ingest_receipt_image_ocr
from app.services.vision_service import is_configured

st.set_page_config(page_title="영수증 업로드 - ledger-lite", page_icon="\U0001F9FE")
require_login()
init_db()
seed_categories()

st.title("\U0001F9FE 영수증 업로드")
st.caption("실물 영수증 사진을 올려주세요. Claude Vision이 자동으로 읽고 분류합니다.")

uploaded = st.file_uploader("영수증 이미지", type=["jpg", "jpeg", "png"])

if uploaded:
    st.image(uploaded, width=300)

    if is_configured():
        if st.button("\U0001F916 AI로 자동 인식 & 등록", type="primary"):
            image_bytes = uploaded.getvalue()
            with st.spinner("Claude Vision으로 영수증을 읽는 중..."):
                image_path = save_receipt_image(image_bytes, uploaded.name)
                result = ingest_receipt_image_ocr(
                    image_path=image_path, image_bytes=image_bytes, filename=uploaded.name
                )
            if result["status"] == "ok":
                category_label = result["major_category"]
                if result.get("minor_category"):
                    category_label += f" > {result['minor_category']}"
                st.success(
                    f"등록 완료: {result['merchant'] or '(가맹점 미인식)'} {result['amount']:,}원 "
                    f"({result['txn_date']}) - {category_label} · 신뢰도 {result['confidence']:.0%}"
                )
                st.caption("'거래내역' 페이지에서 인식 결과를 확인하고 필요하면 수정하세요.")
            else:
                st.warning(f"AI 인식에 실패했습니다: {result['error']}\n아래에서 직접 입력해주세요.")
    else:
        st.info(
            "ANTHROPIC_API_KEY가 설정되지 않아 AI 자동 인식을 사용할 수 없습니다. "
            "아래에서 직접 입력해주세요 (.env에 키를 추가하면 자동 인식이 활성화됩니다)."
        )

    st.divider()
    st.subheader("직접 입력")
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
