import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if p.name == "app").parent))

import streamlit as st

from app.auth import require_login
from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.parsers.kakaopay_parser import split_messages
from app.services.receipt_service import ingest_kakaopay
from app.theme import apply_theme

st.set_page_config(page_title="카카오페이 입력 - ledger-lite", page_icon="\U0001F4B8")
require_login()
apply_theme()
init_db()
seed_categories()

st.title("\U0001F4B8 카카오페이 송금 입력")
st.caption(
    "카카오톡 송금 내역을 복사해 붙여넣으세요. 상대방이 사람 이름이라 가맹점 분류가 불가능하므로 "
    "'라이프스타일비 > 소셜/네트워킹'으로 항상 기본 배정됩니다. '상대방 금액 월/일' 형식은 방향(보냄/받음) "
    "표시가 없어 항상 보낸 것으로 등록되니, 받은 돈이 섞여 있으면 거래내역 페이지에서 방향을 바로잡아주세요."
)

raw = st.text_area(
    "카카오페이 송금 내역 원문 (한 줄에 한 건)",
    height=200,
    placeholder="테니스 6700원 7/3\n이희근 19500 7/3",
)

if st.button("파싱해서 등록", type="primary", disabled=not raw.strip()):
    messages = split_messages(raw)
    if not messages:
        st.warning("인식된 메시지가 없습니다.")
    else:
        ok = dup = fail = 0
        for msg in messages:
            result = ingest_kakaopay(msg)
            if result["status"] == "ok":
                ok += 1
                direction = "보냄" if result["flow_direction"] == "outflow" else "받음"
                st.success(f"등록: [{result['room']}] {result['amount']:,}원 {direction}")
            elif result["status"] == "duplicate":
                dup += 1
                st.info(f"이미 등록된 내역입니다: {msg[:40]}...")
            else:
                fail += 1
                st.error(f"파싱 실패: {result['error']}")
        st.caption(f"총 {len(messages)}건 중 신규 {ok}건 · 중복 {dup}건 · 실패 {fail}건")
