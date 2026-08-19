import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if p.name == "app").parent))

import streamlit as st

from app.auth import require_login
from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.services import kakao_service
from app.services.dashboard_service import available_months, build_monthly_report_text
from app.theme import apply_theme

st.set_page_config(page_title="카카오 알림 - ledger-lite", page_icon="\U0001F4AC")
require_login()
apply_theme()
init_db()
seed_categories()

st.title("\U0001F4AC 카카오 알림")
st.caption("카카오톡 '나에게 보내기'로 월간 리포트를 받아보세요.")

if not kakao_service.is_configured():
    st.info(
        "`KAKAO_REST_API_KEY`가 설정되지 않았습니다. .env에 카카오 개발자 앱의 REST API 키와 "
        "`KAKAO_REDIRECT_URI`를 추가하면 이 기능을 사용할 수 있습니다."
    )
    st.stop()

if kakao_service.is_logged_in():
    st.success("카카오 로그인 상태입니다.")
    if st.button("로그아웃"):
        kakao_service.logout()
        st.rerun()
else:
    st.warning("아직 카카오 로그인을 하지 않았습니다.")
    st.link_button("\U0001F49B 카카오 로그인", kakao_service.build_authorize_url())
    st.caption("버튼을 누르면 카카오 동의 화면으로 이동합니다. 로그인 후 ledger-lite 홈 화면으로 돌아옵니다.")
    st.stop()

st.divider()

months = available_months()
if not months:
    st.info("아직 등록된 거래가 없어 리포트를 만들 수 없습니다.")
    st.stop()

selected_month = st.selectbox("리포트 보낼 월", months, index=0)
report_text = build_monthly_report_text(selected_month)
st.text_area("미리보기", report_text, height=220, disabled=True)

if st.button("\U0001F4E4 카카오톡으로 보내기", type="primary"):
    try:
        kakao_service.send_memo_to_me(report_text)
        st.success("카카오톡으로 리포트를 보냈습니다. '나에게 보내기' 채팅방을 확인해보세요.")
    except kakao_service.KakaoAuthError as e:
        st.error(f"{e}")
    except kakao_service.KakaoRequestError as e:
        st.error(f"전송 실패: {e}")
