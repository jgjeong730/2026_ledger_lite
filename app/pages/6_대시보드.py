import calendar as pycalendar
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if p.name == "app").parent))

import plotly.graph_objects as go
import streamlit as st

from app.auth import require_login
from app.db.connection import init_db
from app.db.seed_categories import seed_categories
from app.services.dashboard_service import (
    available_months,
    available_weeks,
    cumulative_summary,
    daily_expense_in_range,
    expense_by_category,
    expense_by_category_range,
    expense_by_major_category,
    expense_by_major_category_range,
    monthly_summary,
    monthly_trend,
    range_summary,
    week_range,
)

st.set_page_config(page_title="대시보드 - ledger-lite", page_icon="\U0001F4CA", layout="wide")
require_login()
init_db()
seed_categories()

# 대분류 고정 배색 (dataviz 스킬 카테고리컬 팔레트, 라이트모드 슬롯 1~5 - 앱 테마가 라이트라서 라이트
# 서피스 기준 대비를 통과하는 값을 쓴다). categories 시드 순서와 동일하게 항상 같은 대분류가 같은
# 색을 갖도록 고정한다 - 대분류가 늘거나 줄어도 나머지 배색은 흔들리지 않는다.
MAJOR_CATEGORY_COLORS = {
    "고정비": "#2a78d6",
    "변동비": "#eb6834",
    "라이프스타일비": "#1baf7a",
    "가족·경조사비": "#eda100",
    "비정기 대형지출": "#e87ba4",
    "미분류·확인필요": "#898781",  # 시스템 상태값 - 카테고리컬 슬롯이 아니라 무채색 muted로 구분
}
EXPENSE_COLOR = "#2a78d6"
INCOME_COLOR = "#1baf7a"
GRID_COLOR = "#e1e0d9"
TEXT_COLOR = "#52514e"
TEXT_FAINT = "#9a9689"
SUNDAY_COLOR = "#c0574f"
SATURDAY_COLOR = "#2f6fb0"
TODAY_BG = "#e6eef8"
HAS_SPEND_BG = "#faf6ec"

CHART_LAYOUT_DEFAULTS = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=TEXT_COLOR, family="system-ui, -apple-system, 'Segoe UI', sans-serif"),
    margin=dict(l=10, r=10, t=10, b=10),
)


def _calendar_html(month: str, daily: dict[str, int]) -> str:
    """month('YYYY-MM')의 일요일 시작 달력을 HTML 테이블로 그린다. 지출이 있는 날은 금액을,
    오늘 날짜는 옅은 파란 배경으로 표시한다."""
    year, mon = int(month[:4]), int(month[5:7])
    weeks = pycalendar.Calendar(firstweekday=6).monthdayscalendar(year, mon)
    today_str = date.today().isoformat()

    headers = ["일", "월", "화", "수", "목", "금", "토"]
    header_html = "".join(
        f'<th style="padding:6px 4px;font-size:11px;font-weight:600;'
        f'color:{SUNDAY_COLOR if i == 0 else SATURDAY_COLOR if i == 6 else TEXT_FAINT};">{h}</th>'
        for i, h in enumerate(headers)
    )

    rows_html = ""
    for week in weeks:
        cells = ""
        for i, day in enumerate(week):
            if day == 0:
                cells += '<td style="padding:6px 2px;"></td>'
                continue
            day_str = f"{year:04d}-{mon:02d}-{day:02d}"
            amount = daily.get(day_str, 0)
            is_today = day_str == today_str
            num_color = SUNDAY_COLOR if i == 0 else SATURDAY_COLOR if i == 6 else TEXT_COLOR
            bg = TODAY_BG if is_today else (HAS_SPEND_BG if amount else "transparent")
            amount_html = (
                f'<div style="font-size:10px;color:{EXPENSE_COLOR};font-weight:700;margin-top:2px;">{amount:,.0f}</div>'
                if amount
                else ""
            )
            cells += (
                f'<td style="padding:6px 2px;text-align:center;vertical-align:top;'
                f'background:{bg};border-radius:8px;">'
                f'<div style="font-size:12px;color:{num_color};font-weight:{700 if is_today else 400};">{day}</div>'
                f"{amount_html}</td>"
            )
        rows_html += f"<tr>{cells}</tr>"

    return (
        '<table style="width:100%;border-collapse:collapse;">'
        f"<thead><tr>{header_html}</tr></thead><tbody>{rows_html}</tbody></table>"
    )


st.title("\U0001F4CA 대시보드")

months = available_months()
if not months:
    st.info(
        "아직 등록된 거래가 없습니다. 카드문자·카카오페이·영수증·은행이체 페이지에서 "
        "거래를 먼저 등록해주세요."
    )
    st.stop()

# ============================================================
# 누적 현황 (오늘 기준 이번 주/이번 달/올해 누적 지출)
# ============================================================
cum = cumulative_summary()
cum_col1, cum_col2, cum_col3 = st.columns(3)
cum_col1.metric("이번 주 누적", f"{cum['week_expense']:,}원")
cum_col2.metric("이번 달 누적", f"{cum['month_expense']:,}원")
cum_col3.metric("올해 누적", f"{cum['year_expense']:,}원")

st.divider()

# ============================================================
# 최근 6개월 지출·수입 추이 (지점마다 금액 라벨 표시)
# ============================================================
st.subheader("최근 6개월 지출·수입 추이")
trend = monthly_trend(6)
trend_expense = [t["expense"] for t in trend]
trend_income = [t["income"] for t in trend]
fig_trend = go.Figure()
fig_trend.add_trace(
    go.Scatter(
        x=[t["month"] for t in trend],
        y=trend_expense,
        mode="lines+markers+text",
        name="지출",
        line=dict(color=EXPENSE_COLOR, width=2),
        marker=dict(size=8),
        text=[f"{v:,.0f}" for v in trend_expense],
        textposition="top center",
        textfont=dict(size=10, color=EXPENSE_COLOR),
        hovertemplate="%{x} 지출 %{y:,.0f}원<extra></extra>",
    )
)
fig_trend.add_trace(
    go.Scatter(
        x=[t["month"] for t in trend],
        y=trend_income,
        mode="lines+markers+text",
        name="수입",
        line=dict(color=INCOME_COLOR, width=2),
        marker=dict(size=8),
        text=[f"{v:,.0f}" for v in trend_income],
        textposition="bottom center",
        textfont=dict(size=10, color=INCOME_COLOR),
        hovertemplate="%{x} 수입 %{y:,.0f}원<extra></extra>",
    )
)
fig_trend.update_layout(
    **CHART_LAYOUT_DEFAULTS,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    yaxis=dict(gridcolor=GRID_COLOR, tickformat=",.0f", zeroline=False, rangemode="tozero"),
    xaxis=dict(type="category", gridcolor="rgba(0,0,0,0)"),  # "YYYY-MM"을 날짜로 오인해 주단위로 쪼개는 것 방지
    hovermode="x unified",
    height=340,
)
st.plotly_chart(fig_trend, use_container_width=True)

st.divider()

# ============================================================
# 기간 선택 (월간/주간)
# ============================================================
period_type = st.radio("기간", ["월간", "주간"], horizontal=True)

if period_type == "월간":
    selected_month = st.selectbox("월 선택", months, index=0)
    summary = monthly_summary(selected_month)
    major_rows = expense_by_major_category(selected_month)
    detail_rows = expense_by_category(selected_month)
    year, mon = int(selected_month[:4]), int(selected_month[5:7])
    period_start = f"{selected_month}-01"
    period_end = f"{selected_month}-{pycalendar.monthrange(year, mon)[1]:02d}"
    period_label = selected_month
else:
    weeks = available_weeks()
    week_bounds = {w: week_range(w) for w in weeks}
    selected_week = st.selectbox(
        "주 선택", weeks, index=0, format_func=lambda w: f"{week_bounds[w][0][5:]} ~ {week_bounds[w][1][5:]}"
    )
    period_start, period_end = week_bounds[selected_week]
    summary = range_summary(period_start, period_end)
    major_rows = expense_by_major_category_range(period_start, period_end)
    detail_rows = expense_by_category_range(period_start, period_end)
    period_label = f"{period_start} ~ {period_end}"

col1, col2, col3, col4 = st.columns(4)
col1.metric("지출", f"{summary['expense']:,}원")
col2.metric("수입", f"{summary['income']:,}원")
col3.metric("순증감", f"{summary['net']:+,}원")
col4.metric("확인 필요", f"{summary['needs_review']}건")

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("대분류별 지출 비중")
    if not major_rows:
        st.caption("이 기간에는 지출 내역이 없습니다.")
    else:
        majors = [r["major_category"] for r in major_rows]
        amounts = [r["amount"] for r in major_rows]
        total_expense = sum(amounts)
        fig_donut = go.Figure(
            go.Pie(
                labels=majors,
                values=amounts,
                hole=0.62,
                sort=False,
                marker=dict(
                    colors=[MAJOR_CATEGORY_COLORS.get(m, EXPENSE_COLOR) for m in majors],
                    line=dict(color="#ffffff", width=2),
                ),
                textinfo="percent",
                textfont=dict(size=12, color="#ffffff"),
                hovertemplate="%{label} %{value:,.0f}원 (%{percent})<extra></extra>",
            )
        )
        fig_donut.update_layout(
            **CHART_LAYOUT_DEFAULTS,
            showlegend=True,
            legend=dict(orientation="h", yanchor="top", y=-0.05, font=dict(size=11)),
            height=300,
            annotations=[
                dict(
                    text=f"{total_expense:,.0f}<br>원",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=15, color=TEXT_COLOR),
                )
            ],
        )
        st.plotly_chart(fig_donut, use_container_width=True)

with col_right:
    st.subheader("소분류 지출 TOP 10")
    top10 = detail_rows[:10]
    if not top10:
        st.caption("이 기간에는 지출 내역이 없습니다.")
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
            height=300,
        )
        st.plotly_chart(fig_minor, use_container_width=True)

st.divider()

# ============================================================
# 날짜별 보기: 월간은 달력, 주간은 요일별 막대
# ============================================================
daily = daily_expense_in_range(period_start, period_end)
if period_type == "월간":
    st.subheader(f"{period_label} 날짜별 지출")
    st.markdown(_calendar_html(selected_month, daily), unsafe_allow_html=True)
else:
    st.subheader("이번 주 날짜별 지출")
    week_dates = [(date.fromisoformat(period_start) + timedelta(days=i)).isoformat() for i in range(7)]
    weekday_names = ["월", "화", "수", "목", "금", "토", "일"]
    week_amounts = [daily.get(d, 0) for d in week_dates]
    fig_week = go.Figure(
        go.Bar(
            x=[f"{wd} {d[5:]}" for wd, d in zip(weekday_names, week_dates)],
            y=week_amounts,
            marker_color=[
                SUNDAY_COLOR if i == 6 else SATURDAY_COLOR if i == 5 else EXPENSE_COLOR for i in range(7)
            ],
            text=[f"{a:,.0f}" if a else "" for a in week_amounts],
            textposition="outside",
            hovertemplate="%{x} %{y:,.0f}원<extra></extra>",
        )
    )
    fig_week.update_layout(
        **CHART_LAYOUT_DEFAULTS,
        yaxis=dict(gridcolor=GRID_COLOR, tickformat=",.0f", zeroline=False, rangemode="tozero"),
        xaxis=dict(gridcolor="rgba(0,0,0,0)"),
        showlegend=False,
        height=280,
    )
    st.plotly_chart(fig_week, use_container_width=True)

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
    st.caption("이 기간에는 지출 내역이 없습니다.")
