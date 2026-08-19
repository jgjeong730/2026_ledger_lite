"""공통 커스텀 CSS 적용. 각 페이지 스크립트가 require_login() 직후 apply_theme()을
호출한다 (멀티페이지 앱은 페이지마다 스크립트가 독립 실행되므로 매번 주입 필요)."""

from pathlib import Path

import streamlit as st

_CSS_PATH = Path(__file__).parent / "static" / "style.css"


def apply_theme() -> None:
    css = _CSS_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
