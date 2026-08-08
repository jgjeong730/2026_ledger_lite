"""ledger-lite Streamlit 진입점 (홈 화면).

입력 채널별 화면은 app/pages/ 각 페이지에서 담당한다:
    1_카드문자_입력, 2_카카오페이_입력, 3_영수증_업로드, 4_은행이체_수동입력, 5_거래내역, 6_대시보드, 7_카카오_알림

카카오 개발자 콘솔에 등록된 Redirect URI가 이 홈 화면(KAKAO_REDIRECT_URI, 기본
http://localhost:8501)으로 고정되어 있어, 로그인 콜백(?code=...)은 여기서 받는다.
"""

import streamlit as st

from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.services import kakao_service
from app.services.receipt_service import list_receipts, summary_counts

st.set_page_config(page_title="ledger-lite", page_icon="\U0001F4B0")

init_db()
seed_categories()

if "code" in st.query_params:
    code = st.query_params["code"]
    st.query_params.clear()
    try:
        kakao_service.exchange_code_for_token(code)
        st.success("카카오 로그인이 완료되었습니다. '카카오 알림' 페이지에서 리포트를 보낼 수 있어요.")
    except Exception as e:
        st.error(f"카카오 로그인 처리 중 오류가 발생했습니다: {e}")

st.title("\U0001F4B0 ledger-lite")
st.caption("찍고 → AI가 읽고 → 자동 분류 → 대시보드로 확인 → 카카오톡으로 리포트 받기")

counts = summary_counts()
col1, col2, col3 = st.columns(3)
col1.metric("이번 달 지출", f"{counts['this_month_expense']:,}원")
col2.metric("전체 거래 건수", f"{counts['total_receipts']}건")
col3.metric("확인 필요", f"{counts['needs_review']}건")

if counts["needs_review"] > 0:
    st.warning(f"미분류/확인 대기 중인 거래가 {counts['needs_review']}건 있습니다. 왼쪽 '거래내역' 페이지에서 확인하세요.")

st.divider()
st.subheader("입력하기")
st.markdown(
    "- **\U0001F4F1 카드문자 입력** — 카드 승인문자 붙여넣기 (자동 파싱)\n"
    "- **\U0001F4B8 카카오페이 입력** — 송금 내역 붙여넣기 (소셜/네트워킹 자동 배정)\n"
    "- **\U0001F9FE 영수증 업로드** — 영수증 사진 업로드, Claude Vision이 자동 인식/분류 (키 없으면 직접 입력)\n"
    "- **\U0001F3E6 은행이체 수동입력** — 계좌이체/출금, 연금인출유입/기타수입\n"
    "- **\U0001F4CB 거래내역** — 전체 내역 확인 및 카테고리 재분류\n"
    "- **\U0001F4CA 대시보드** — 월별 지출·수입 추이, 카테고리별 분석\n"
    "- **\U0001F4AC 카카오 알림** — 카카오 로그인 후 월간 리포트를 카카오톡으로 받기\n"
    "\n왼쪽 사이드바에서 페이지를 선택하세요."
)

recent = list_receipts(limit=5)
if recent:
    st.divider()
    st.subheader("최근 거래")
    for r in recent:
        icon = "\U0001F53B" if r["flow_direction"] == "outflow" else "\U0001F53A"
        category = (r["major_category"] or "미분류") + (
            f" > {r['minor_category']}" if r["minor_category"] else ""
        )
        st.write(f"{icon} {r['transaction_date']} · {r['merchant_name'] or '-'} · {r['amount']:,}원 · {category}")
