"""전체 앱 비밀번호 게이트. APP_PASSWORD가 설정된 경우에만 동작하며, 각 페이지 스크립트가
st.set_page_config() 직후 require_login()을 호출해 인증 전에는 나머지 내용을 그리지 않는다.
st.session_state는 같은 브라우저 세션 내 페이지 이동 시 유지되므로 한 번 인증하면 다른
페이지로 이동해도 다시 묻지 않는다."""

import streamlit as st

from app import config


def require_login() -> None:
    if not config.APP_PASSWORD:
        return
    if st.session_state.get("authenticated"):
        return

    st.title("\U0001F512 ledger-lite")
    password = st.text_input("비밀번호", type="password")
    if st.button("입장"):
        if password == config.APP_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()
