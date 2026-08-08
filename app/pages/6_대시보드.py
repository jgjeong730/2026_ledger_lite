import plotly.graph_objects as go
import streamlit as st

from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.services.dashboard_service import (
    available_months,
    expense_by_category,
    expense_by_major_category,
    monthly_summary,
    monthly_trend,
)

st.set_page_config(page_title="대시보드 - ledger-lite", page_icon="\U0001F4CA", layout="wide")
init_db()
seed_categories()

# 대분류 고정 배색 (dataviz 스킬 카테고리컬 팔레트, 다크모드 슬롯 1~5). categories 시드 순서와 동일하게
# 항상 같은 대분류가 같은 색을 갖도록 고정한다 - 대분류가 늘거나 줄어도 나머지 배색은 흔들리지 않는다.
MAJOR_CATEGORY_COLORS = {
    "고정비": "#3987e5",
    "변동비": "#d95926",
    "라이프스타일비": "#199e70",
    "가족·경조사비": "#c98500",
    "비정기 대형지출": "#d55181",
    "미분류·확인필요": "#898781",  # 시스템 상태값 - 카테고리컬 슬롯이 아니라 무채색 muted로 구분
}
EXPENSE_COLOR = "#3987e5"
INCOME_COLOR = "#199e70"
GRID_COLOR = "#2c2c2a"
TEXT_COLOR = "#c3c2b7"

CHART_LAYOUT_DEFAULTS = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=TEXT_COLOR, family="system-ui, -apple-system, 'Segoe UI', sans-serif"),
    margin=dict(l=10, r=10, t=10, b=10),
)

st.title("\U0001F4CA 대시보드")

months = available_months()
if not months:
    st.info(
        "아직 등록된 거래가 없습니다. 카드문자·카카오페이·영수증·은행이체 페이지에서 "
        "거래를 먼저 등록해주세요."
    )
    st.stop()

st.subheader("최근 6개월 지출·수입 추이")
trend = monthly_trend(6)
fig_trend = go.Figure()
fig_trend.add_trace(
    go.Scatter(
        x=[t["month"] for t in trend],
        y=[t["expense"] for t in trend],
        mode="lines+markers",
        name="지출",
        line=dict(color=EXPENSE_COLOR, width=2),
        marker=dict(size=8),
        hovertemplate="%{x} 지출 %{y:,.0f}원<extra></extra>",
    )
)
fig_trend.add_trace(
    go.Scatter(
        x=[t["month"] for t in trend],
        y=[t["income"] for t in trend],
        mode="lines+markers",
        name="수입",
        line=dict(color=INCOME_COLOR, width=2),
        marker=dict(size=8),
        hovertemplate="%{x} 수입 %{y:,.0f}원<extra></extra>",
    )
)
fig_trend.update_layout(
    **CHART_LAYOUT_DEFAULTS,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    yaxis=dict(gridcolor=GRID_COLOR, tickformat=",.0f", zeroline=False, rangemode="tozero"),
    xaxis=dict(type="category", gridcolor="rgba(0,0,0,0)"),  # "YYYY-MM"을 날짜로 오인해 주단위로 쪼개는 것 방지
    hovermode="x unified",
    height=320,
)
st.plotly_chart(fig_trend, use_container_width=True)

st.divider()

selected_month = st.selectbox("월 선택", months, index=0)

summary = monthly_summary(selected_month)
col1, col2, col3, col4 = st.columns(4)
col1.metric("지출", f"{summary['expense']:,}원")
col2.metric("수입", f"{summary['income']:,}원")
col3.metric("순증감", f"{summary['net']:+,}원")
col4.metric("확인 필요", f"{summary['needs_review']}건")

major_rows = expense_by_major_category(selected_month)
detail_rows = expense_by_category(selected_month)

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("대분류별 지출")
    if not major_rows:
        st.caption("이 달에는 지출 내역이 없습니다.")
    else:
        majors = [r["major_category"] for r in major_rows]
        amounts = [r["amount"] for r in major_rows]
        fig_major = go.Figure(
            go.Bar(
                x=amounts,
                y=majors,
                orientation="h",
                marker_color=[MAJOR_CATEGORY_COLORS.get(m, EXPENSE_COLOR) for m in majors],
                text=[f"{a:,.0f}원" for a in amounts],
                textposition="outside",
                hovertemplate="%{y} %{x:,.0f}원<extra></extra>",
            )
        )
        fig_major.update_layout(
            **CHART_LAYOUT_DEFAULTS,
            xaxis=dict(gridcolor=GRID_COLOR, tickformat=",.0f", zeroline=False),
            yaxis=dict(autorange="reversed", gridcolor="rgba(0,0,0,0)"),
            showlegend=False,
            bargap=0.35,
            height=280,
        )
        st.plotly_chart(fig_major, use_container_width=True)

with col_right:
    st.subheader("소분류 지출 TOP 10")
    top10 = detail_rows[:10]
    if not top10:
        st.caption("이 달에는 지출 내역이 없습니다.")
    else:
        labels = [
            r["major_category"] if not r["minor_category"] else f"{r['major_category']}>{r['minor_category']}"
            for r in top10
        ]
        amounts = [r["amount"] for r in top10]
        fig_minor = go.Figure(
            go.Bar(
                x=amounts,
                y=labels,
                orientation="h",
                marker_color=EXPENSE_COLOR,
                text=[f"{a:,.0f}원" for a in amounts],
                textposition="outside",
                hovertemplate="%{y} %{x:,.0f}원<extra></extra>",
            )
        )
        fig_minor.update_layout(
            **CHART_LAYOUT_DEFAULTS,
            xaxis=dict(gridcolor=GRID_COLOR, tickformat=",.0f", zeroline=False),
            yaxis=dict(autorange="reversed", gridcolor="rgba(0,0,0,0)"),
            showlegend=False,
            bargap=0.35,
            height=280,
        )
        st.plotly_chart(fig_minor, use_container_width=True)

st.divider()
st.subheader("카테고리별 상세")
if detail_rows:
    total = sum(r["amount"] for r in detail_rows) or 1
    table = [
        {
            "대분류": r["major_category"],
            "소분류": r["minor_category"] or "-",
            "금액": r["amount"],
            "비중": f"{r['amount'] / total:.1%}",
        }
        for r in detail_rows
    ]
    st.dataframe(table, use_container_width=True, hide_index=True)
else:
    st.caption("이 달에는 지출 내역이 없습니다.")
