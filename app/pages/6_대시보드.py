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
    MAJOR_CATEGORY_ORDER,
    available_months,
    cumulative_summary,
    daily_expense_in_range,
    expense_by_category_range,
    expense_by_major_category_range,
    monthly_trend_since,
    weekly_trend_since,
)

st.set_page_config(page_title="대시보드 - ledger-lite", page_icon="\U0001F4CA", layout="wide")
require_login()
init_db()
seed_categories()

# 실제 거래 기록을 시작한 날짜 - 이전 달/주는 데이터가 없을 걸 알기 때문에 추이 그래프에서
# 빈 공간으로 채우지 않고 아예 표시 범위에서 제외한다.
TREND_START_DATE = date(2026, 7, 1)
TREND_START_MONTH = TREND_START_DATE.strftime("%Y-%m")

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

ALL_MAJOR_OPTIONS = [*MAJOR_CATEGORY_ORDER, "미분류·확인필요"]


def _shift_month(year_month: str, delta: int) -> str:
    y, m = int(year_month[:4]), int(year_month[5:7])
    m += delta
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def _month_bounds(year_month: str) -> tuple[str, str]:
    y, m = int(year_month[:4]), int(year_month[5:7])
    last_day = pycalendar.monthrange(y, m)[1]
    return f"{year_month}-01", f"{year_month}-{last_day:02d}"


def _summary_table_html(cum: dict) -> str:
    """이번 주/이번 달/올해 x 수입/지출/순증감 요약을 작은 글씨 표로 그린다 (수입이 맨 위)."""
    periods = [("이번 주", "week"), ("이번 달", "month"), ("올해", "year")]
    rows = [("수입", "income"), ("지출", "expense"), ("순증감", "net")]

    header_html = f'<th style="text-align:left;padding:8px 10px;font-size:12px;color:{TEXT_FAINT};"></th>'
    header_html += "".join(
        f'<th style="text-align:right;padding:8px 10px;font-size:12px;color:{TEXT_FAINT};">{label}</th>'
        for label, _ in periods
    )

    body_html = ""
    for row_label, row_key in rows:
        cells = (
            f'<td style="padding:8px 10px;font-size:13px;color:{TEXT_COLOR};font-weight:600;">{row_label}</td>'
        )
        for _, period_key in periods:
            value = cum[f"{period_key}_{row_key}"]
            sign = "+" if row_key == "net" and value >= 0 else ""
            cells += (
                f'<td style="padding:8px 10px;font-size:13px;color:{TEXT_COLOR};text-align:right;">'
                f"{sign}{value:,}원</td>"
            )
        body_html += f'<tr style="border-top:1px solid {GRID_COLOR};">{cells}</tr>'

    return (
        '<table style="width:100%;border-collapse:collapse;">'
        f"<thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>"
    )


def _calendar_html(month: str, daily: dict[str, int]) -> str:
    """month('YYYY-MM')의 일요일 시작 달력을 HTML 테이블로 그린다. 지출이 있는 날은 금액을,
    오늘 날짜는 옅은 파란 배경으로 표시한다."""
    year, mon = int(month[:4]), int(month[5:7])
    weeks = pycalendar.Calendar(firstweekday=6).monthdayscalendar(year, mon)
    today_str = date.today().isoformat()

    headers = ["일", "월", "화", "수", "목", "금", "토"]
    header_html = "".join(
        f'<th style="padding:10px 4px;font-size:13px;font-weight:600;'
        f'color:{SUNDAY_COLOR if i == 0 else SATURDAY_COLOR if i == 6 else TEXT_FAINT};">{h}</th>'
        for i, h in enumerate(headers)
    )

    rows_html = ""
    for week in weeks:
        cells = ""
        for i, day in enumerate(week):
            if day == 0:
                cells += '<td style="padding:12px 4px;"></td>'
                continue
            day_str = f"{year:04d}-{mon:02d}-{day:02d}"
            amount = daily.get(day_str, 0)
            is_today = day_str == today_str
            num_color = SUNDAY_COLOR if i == 0 else SATURDAY_COLOR if i == 6 else TEXT_COLOR
            bg = TODAY_BG if is_today else (HAS_SPEND_BG if amount else "transparent")
            amount_html = (
                f'<div style="font-size:13px;color:{EXPENSE_COLOR};font-weight:700;margin-top:4px;">{amount:,.0f}</div>'
                if amount
                else ""
            )
            cells += (
                f'<td style="padding:12px 4px;text-align:center;vertical-align:top;'
                f'background:{bg};border-radius:10px;">'
                f'<div style="font-size:15px;color:{num_color};font-weight:{700 if is_today else 400};">{day}</div>'
                f"{amount_html}</td>"
            )
        rows_html += f"<tr>{cells}</tr>"

    return (
        '<table style="width:100%;border-collapse:collapse;">'
        f"<thead><tr>{header_html}</tr></thead><tbody>{rows_html}</tbody></table>"
    )


def _detail_table_html(rows: list[dict]) -> str:
    """카테고리별 상세 표를 금액 천원 단위 + 중앙정렬 + 맨 아래 합계행으로 그린다."""
    total = sum(r["amount"] for r in rows) or 1
    header_html = (
        '<tr>'
        '<th style="text-align:left;padding:8px 10px;font-size:12px;color:{c};">대분류</th>'
        '<th style="text-align:left;padding:8px 10px;font-size:12px;color:{c};">소분류</th>'
        '<th style="text-align:center;padding:8px 10px;font-size:12px;color:{c};">금액(천원)</th>'
        '<th style="text-align:center;padding:8px 10px;font-size:12px;color:{c};">비중</th>'
        "</tr>"
    ).format(c=TEXT_FAINT)

    body_html = ""
    for r in rows:
        pct = r["amount"] / total
        body_html += (
            '<tr style="border-top:1px solid {grid};">'
            '<td style="padding:8px 10px;font-size:13px;color:{tc};">{major}</td>'
            '<td style="padding:8px 10px;font-size:13px;color:{tc};">{minor}</td>'
            '<td style="padding:8px 10px;font-size:13px;color:{tc};text-align:center;">{amount:,.0f}</td>'
            '<td style="padding:8px 10px;font-size:13px;color:{tc};text-align:center;">{pct:.1%}</td>'
            "</tr>"
        ).format(
            grid=GRID_COLOR,
            tc=TEXT_COLOR,
            major=r["major_category"],
            minor=r["minor_category"] or "-",
            amount=r["amount"] / 1000,
            pct=pct,
        )

    footer_html = (
        '<tr style="border-top:2px solid {grid};font-weight:700;">'
        '<td style="padding:8px 10px;font-size:13px;color:{tc};" colspan="2">합계</td>'
        '<td style="padding:8px 10px;font-size:13px;color:{tc};text-align:center;">{amount:,.0f}</td>'
        '<td style="padding:8px 10px;font-size:13px;color:{tc};text-align:center;">100.0%</td>'
        "</tr>"
    ).format(grid=TEXT_COLOR, tc=TEXT_COLOR, amount=sum(r["amount"] for r in rows) / 1000)

    return (
        '<table style="width:100%;border-collapse:collapse;">'
        f"<thead>{header_html}</thead><tbody>{body_html}{footer_html}</tbody></table>"
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
# 누적 현황 (오늘 기준 이번 주/이번 달/올해 누적 수입·지출·순증감, 표)
# ============================================================
cum = cumulative_summary()
st.markdown(_summary_table_html(cum), unsafe_allow_html=True)

st.divider()

# ============================================================
# 지출·수입 추이 (주간/월간 막대그래프, 2026-07-01부터)
# ============================================================
st.subheader("지출·수입 추이")
trend_mode = st.radio("추이 기간", ["월간", "주간"], horizontal=True, label_visibility="collapsed")

today = date.today()
if trend_mode == "월간":
    trend = monthly_trend_since(TREND_START_MONTH)
    x_labels = [t["month"] for t in trend]
    period_start, period_end = _month_bounds(today.strftime("%Y-%m"))
else:
    trend = weekly_trend_since(TREND_START_DATE.isoformat())
    x_labels = [f"{t['week_start'][5:]}~" for t in trend]
    period_start = (today - timedelta(days=today.weekday())).isoformat()
    period_end = (date.fromisoformat(period_start) + timedelta(days=6)).isoformat()

trend_expense = [t["expense"] for t in trend]
trend_income = [t["income"] for t in trend]
fig_trend = go.Figure()
fig_trend.add_trace(
    go.Bar(
        x=x_labels, y=trend_income, name="수입", marker_color=INCOME_COLOR,
        hovertemplate="%{x} 수입 %{y:,.0f}원<extra></extra>",
    )
)
fig_trend.add_trace(
    go.Bar(
        x=x_labels, y=trend_expense, name="지출", marker_color=EXPENSE_COLOR,
        hovertemplate="%{x} 지출 %{y:,.0f}원<extra></extra>",
    )
)
fig_trend.update_layout(
    **CHART_LAYOUT_DEFAULTS,
    barmode="group",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    yaxis=dict(gridcolor=GRID_COLOR, tickformat=",.0f", zeroline=False, rangemode="tozero"),
    xaxis=dict(type="category", gridcolor="rgba(0,0,0,0)"),
    hovermode="x unified",
    height=340,
)
st.plotly_chart(fig_trend, use_container_width=True)

# ============================================================
# 대분류 제외 필터 (기본: 전체 포함) - 대분류별 지출 비중/TOP10/카테고리별 상세에 적용됨
# ============================================================
exclude_majors = st.multiselect(
    "분석에서 제외할 대분류 (비정기 대형지출처럼 일상적이지 않은 큰 지출을 빼고 보고 싶을 때 선택 - "
    "아래 대분류별 지출 비중·소분류 TOP10·카테고리별 상세에 적용됩니다)",
    options=ALL_MAJOR_OPTIONS,
)

major_rows = expense_by_major_category_range(period_start, period_end, exclude_majors=exclude_majors)
detail_rows = expense_by_category_range(period_start, period_end, exclude_majors=exclude_majors)

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
# 날짜별 지출 (캘린더, 자체 월 이동)
# ============================================================
if "dash_calendar_month" not in st.session_state:
    st.session_state.dash_calendar_month = today.strftime("%Y-%m")

cal_prev, cal_title, cal_next = st.columns([1, 6, 1])
if cal_prev.button("◀", key="cal_prev_btn"):
    st.session_state.dash_calendar_month = _shift_month(st.session_state.dash_calendar_month, -1)
    st.rerun()
cal_title.markdown(f"<h4 style='text-align:center;'>{st.session_state.dash_calendar_month} 날짜별 지출</h4>", unsafe_allow_html=True)
if cal_next.button("▶", key="cal_next_btn"):
    st.session_state.dash_calendar_month = _shift_month(st.session_state.dash_calendar_month, 1)
    st.rerun()

cal_start, cal_end = _month_bounds(st.session_state.dash_calendar_month)
cal_daily = daily_expense_in_range(cal_start, cal_end)
st.markdown(_calendar_html(st.session_state.dash_calendar_month, cal_daily), unsafe_allow_html=True)

st.divider()

# ============================================================
# 카테고리별 상세 (자체 월 이동, 천원 단위, 중앙정렬, 합계행)
# ============================================================
if "dash_detail_month" not in st.session_state:
    st.session_state.dash_detail_month = today.strftime("%Y-%m")

det_prev, det_title, det_next = st.columns([1, 6, 1])
if det_prev.button("◀", key="detail_prev_btn"):
    st.session_state.dash_detail_month = _shift_month(st.session_state.dash_detail_month, -1)
    st.rerun()
det_title.markdown(f"<h4 style='text-align:center;'>{st.session_state.dash_detail_month} 카테고리별 상세</h4>", unsafe_allow_html=True)
if det_next.button("▶", key="detail_next_btn"):
    st.session_state.dash_detail_month = _shift_month(st.session_state.dash_detail_month, 1)
    st.rerun()

if exclude_majors:
    st.caption(f"제외된 대분류: {', '.join(exclude_majors)}")

det_start, det_end = _month_bounds(st.session_state.dash_detail_month)
detail_month_rows = expense_by_category_range(det_start, det_end, exclude_majors=exclude_majors)
if detail_month_rows:
    st.markdown(_detail_table_html(detail_month_rows), unsafe_allow_html=True)
else:
    st.caption("이 기간에는 지출 내역이 없습니다.")
