import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if p.name == "app").parent))

import pandas as pd
import streamlit as st

from app.auth import require_login
from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.services.dashboard_service import available_months
from app.services.receipt_service import list_receipts_for_month

st.set_page_config(page_title="백업 - ledger-lite", page_icon="\U0001F4BE")
require_login()
init_db()
seed_categories()

st.title("\U0001F4BE 백업")
st.caption("선택한 달의 거래내역을 CSV로 내려받습니다. 매달 초 지난달 데이터를 백업해두는 걸 추천합니다.")

today = date.today()
last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

months = available_months()
if not months:
    st.info("아직 등록된 거래가 없습니다.")
    st.stop()

default_index = months.index(last_month) if last_month in months else 0
selected_month = st.selectbox("백업할 월", months, index=default_index)

rows = list_receipts_for_month(selected_month)
if not rows:
    st.caption("이 달에는 거래가 없습니다.")
    st.stop()

df = pd.DataFrame(rows).rename(
    columns={
        "id": "ID",
        "entry_type": "구분",
        "source_type": "입력경로",
        "flow_direction": "방향",
        "merchant_name": "가맹점/내용",
        "amount": "금액",
        "transaction_date": "거래일",
        "transaction_time": "거래시각",
        "memo": "메모",
        "review_status": "확인상태",
        "is_manual_entry": "수동입력여부",
        "major_category": "대분류",
        "minor_category": "소분류",
        "classified_by": "분류방식",
    }
)
st.dataframe(df, use_container_width=True, hide_index=True)

csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    f"\U0001F4E5 {selected_month} 백업 다운로드 (CSV)",
    data=csv_bytes,
    file_name=f"ledger-lite_{selected_month}.csv",
    mime="text/csv",
)
