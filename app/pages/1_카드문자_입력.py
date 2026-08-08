import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if p.name == "app").parent))

import streamlit as st

from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.parsers.card_sms_parser import split_messages
from app.services.receipt_service import ingest_card_sms

st.set_page_config(page_title="카드문자 입력 - ledger-lite", page_icon="\U0001F4F1")
init_db()
seed_categories()

st.title("\U0001F4F1 카드 승인문자 입력")
st.caption(
    "문자 앱에서 카드 승인문자를 복사해 아래에 붙여넣으세요. 여러 건을 한 번에 붙여넣어도 자동으로 나눠 처리합니다."
)

raw = st.text_area(
    "카드 승인문자 원문",
    height=200,
    placeholder="[Web발신] 현대카드M 승인 정*구 100,000원 일시불 08/08 09:48 대신주유소 누적669,523원",
)

if st.button("파싱해서 등록", type="primary", disabled=not raw.strip()):
    messages = split_messages(raw)
    if not messages:
        st.warning("인식된 메시지가 없습니다. [Web발신]으로 시작하는 문자인지 확인해주세요.")
    else:
        ok = dup = fail = 0
        for msg in messages:
            result = ingest_card_sms(msg)
            if result["status"] == "ok":
                ok += 1
                basis = {
                    "rule": "학습된 규칙 적용",
                    "ai": "AI 자동 분류(확인 필요)",
                    "default": "미분류(확인 필요)",
                }.get(result["classified_by"], "확인 필요")
                st.success(f"등록: {result['merchant']} {result['amount']:,}원 ({result['txn_date']}) - {basis}")
            elif result["status"] == "duplicate":
                dup += 1
                st.info(f"이미 등록된 문자입니다: {msg[:40]}...")
            else:
                fail += 1
                st.error(f"파싱 실패: {result['error']}")
        st.caption(f"총 {len(messages)}건 중 신규 {ok}건 · 중복 {dup}건 · 실패 {fail}건")

st.divider()
st.caption("가맹점별 카테고리는 '거래내역' 페이지에서 재분류하면 다음부터 자동 적용됩니다 (학습 규칙).")
