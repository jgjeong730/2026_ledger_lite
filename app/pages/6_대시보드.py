import calendar as pycalendar
import sys
from datetime import date
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
    daily_expense_in_range,
    expense_by_category_by_months,
    expense_by_category_range,
    expense_by_major_category_by_months,
    monthly_income_expense_by_months,
)
from app.theme import apply_theme

st.set_page_config(page_title="대시보드 - ledger-lite", page_icon="\U0001F4CA", layout="wide")
require_login()
apply_theme()
init_db()
seed_categories()

# 실제 거래 기록을 시작한 날짜 - 2026년 연도별 표/차트는 이 달 이전을 표시 범위에서 제외한다.
TREND_START_DATE = date(2026, 7, 1)

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


def _yearly_table_html(months_data: list[dict]) -> str:
    """선택 연도의 월별(7월/8월/... 또는 1월~12월) x 수입/지출/순증감 표를 그리고, 맨 오른쪽에
    누적합계 열을 덧붙인다 (수입이 맨 위)."""
    rows = [("수입", "income"), ("지출", "expense"), ("순증감", "net")]
    for m in months_data:
        m["net"] = m["income"] - m["expense"]
    cum = {
        "income": sum(m["income"] for m in months_data),
        "expense": sum(m["expense"] for m in months_data),
    }
    cum["net"] = cum["income"] - cum["expense"]

    header_html = f'<th style="text-align:left;padding:8px 10px;font-size:12px;color:{TEXT_FAINT};"></th>'
    header_html += "".join(
        f'<th style="text-align:right;padding:8px 10px;font-size:12px;color:{TEXT_FAINT};">{int(m["month"][5:7])}월</th>'
        for m in months_data
    )
    header_html += (
        f'<th style="text-align:right;padding:8px 10px;font-size:12px;color:{TEXT_FAINT};'
        'font-weight:700;">누적합계</th>'
    )

    body_html = ""
    for row_label, row_key in rows:
        cells = (
            f'<td style="padding:8px 10px;font-size:13px;color:{TEXT_COLOR};font-weight:600;">{row_label}</td>'
        )
        for m in months_data:
            value = m[row_key]
            sign = "+" if row_key == "net" and value >= 0 else ""
            cells += (
                f'<td style="padding:8px 10px;font-size:13px;color:{TEXT_COLOR};text-align:right;">'
                f"{sign}{value:,}</td>"
            )
        cum_value = cum[row_key]
        sign = "+" if row_key == "net" and cum_value >= 0 else ""
        cells += (
            f'<td style="padding:8px 10px;font-size:13px;color:{TEXT_COLOR};text-align:right;'
            f'font-weight:700;background:{HAS_SPEND_BG};">{sign}{cum_value:,}</td>'
        )
        body_html += f'<tr style="border-top:1px solid {GRID_COLOR};">{cells}</tr>'

    return (
        '<div style="overflow-x:auto;">'
        '<table style="width:100%;border-collapse:collapse;min-width:520px;">'
        f"<thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>"
        "</div>"
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
# 연도별 월간 수입/지출/순증감 표 + 누적합계 (연도 선택 가능, 2026년은 실제 기록 시작월인
# 7월부터 표시 - 그 외 연도는 1월~12월 전체)
# ============================================================
today = date.today()
year_options = list(range(TREND_START_DATE.year, max(TREND_START_DATE.year, today.year) + 1))
if "dash_selected_year" not in st.session_state:
    st.session_state.dash_selected_year = today.year if today.year in year_options else year_options[-1]

with st.container(border=True, key="dash_card_summary"):
    year_label_col, year_select_col = st.columns([1, 3], vertical_alignment="center")
    year_label_col.markdown("연도 선택")
    selected_year = year_select_col.selectbox(
        "연도 선택",
        options=year_options,
        format_func=lambda y: f"{y}년",
        index=year_options.index(st.session_state.dash_selected_year),
        key="dash_year_select",
        label_visibility="collapsed",
    )
    st.session_state.dash_selected_year = selected_year

    start_month_num = TREND_START_DATE.month if selected_year == TREND_START_DATE.year else 1
    year_months = [f"{selected_year:04d}-{m:02d}" for m in range(start_month_num, 13)]
    months_data = monthly_income_expense_by_months(year_months)
    st.markdown(_yearly_table_html(months_data), unsafe_allow_html=True)

    # 위 표와 같은 연도/월 범위의 수입·지출만 그리는 월별 막대그래프 (누적합계는 차트에 넣지 않음)
    x_labels = [f"{int(m['month'][5:7])}월" for m in months_data]
    fig_trend = go.Figure()
    trend_income = [m["income"] for m in months_data]
    trend_expense = [m["expense"] for m in months_data]
    fig_trend.add_trace(
        go.Bar(
            x=x_labels, y=trend_income, name="수입", marker_color=INCOME_COLOR,
            text=[f"{v / 1000:,.0f}" for v in trend_income],
            textposition="outside",
            hovertemplate="%{x} 수입 %{y:,.0f}<extra></extra>",
        )
    )
    fig_trend.add_trace(
        go.Bar(
            x=x_labels, y=trend_expense, name="지출", marker_color=EXPENSE_COLOR,
            text=[f"{v / 1000:,.0f}" for v in trend_expense],
            textposition="outside",
            hovertemplate="%{x} 지출 %{y:,.0f}<extra></extra>",
        )
    )
    fig_trend.update_layout(
        **{**CHART_LAYOUT_DEFAULTS, "margin": dict(l=10, r=10, t=30, b=10)},
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(gridcolor=GRID_COLOR, tickformat=",.0f", zeroline=False, rangemode="tozero"),
        xaxis=dict(type="category", gridcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
        uniformtext=dict(minsize=10, mode="hide"),
        height=320,
    )
    st.plotly_chart(fig_trend, use_container_width=True)

st.divider()

# ============================================================
# 대분류 제외 필터 (기본: 전체 포함) - 대분류 지출/소분류 지출 Top 10/카테고리별 상세에 적용됨
# 드롭다운 대신 대분류를 가로로 나열한 토글 버튼(선택=제외)으로 표시한다.
# ============================================================
with st.container(border=True, key="dash_card_filter"):
    st.caption(
        "분석에서 제외할 대분류 (비정기 대형지출처럼 일상적이지 않은 큰 지출을 빼고 보고 싶을 때 클릭 - "
        "아래 대분류 지출·소분류 지출 Top 10·카테고리별 상세에 적용됩니다)"
    )
    exclude_majors = st.pills(
        "분석에서 제외할 대분류",
        options=ALL_MAJOR_OPTIONS,
        selection_mode="multi",
        default=[],
        label_visibility="collapsed",
    ) or []

    # 대분류 지출 - 이 차트만의 독립된 연도 선택 (맨 위 표의 연도와 별개)
    major_title_col, major_year_col = st.columns([3, 1])
    major_title_col.subheader("대분류 지출")
    if "dash_major_chart_year" not in st.session_state:
        st.session_state.dash_major_chart_year = selected_year
    major_chart_year = major_year_col.selectbox(
        "연도",
        options=year_options,
        format_func=lambda y: f"{y}년",
        index=year_options.index(st.session_state.dash_major_chart_year),
        key="dash_major_year_select",
        label_visibility="collapsed",
    )
    st.session_state.dash_major_chart_year = major_chart_year
    major_start_month = TREND_START_DATE.month if major_chart_year == TREND_START_DATE.year else 1
    major_months = [f"{major_chart_year:04d}-{m:02d}" for m in range(major_start_month, 13)]
    major_x_labels = [f"{int(m[5:7])}월" for m in major_months]
    major_by_month_rows = expense_by_major_category_by_months(major_months, exclude_majors=exclude_majors)

    if not major_by_month_rows:
        st.caption("이 기간에는 지출 내역이 없습니다.")
    else:
        by_month_major = {(r["month"], r["major_category"]): r["amount"] for r in major_by_month_rows}
        present_majors = [m for m in ALL_MAJOR_OPTIONS if any(r["major_category"] == m for r in major_by_month_rows)]
        # 그 달에 표시되는 대분류 합계 - hover에 보여줄 비중(%) 계산용 분모
        major_month_totals = {
            m: sum(by_month_major.get((m, mj), 0) for mj in present_majors) for m in major_months
        }
        fig_major = go.Figure()
        for major in present_majors:
            amounts = [by_month_major.get((m, major), 0) for m in major_months]
            pct = [
                (v / major_month_totals[m] * 100) if major_month_totals[m] else 0
                for v, m in zip(amounts, major_months)
            ]
            fig_major.add_trace(
                go.Bar(
                    x=major_x_labels,
                    y=amounts,
                    name=major,
                    marker_color=MAJOR_CATEGORY_COLORS.get(major, EXPENSE_COLOR),
                    customdata=pct,
                    hovertemplate=f"{major} " + "%{y:,.0f} %{customdata:.0f}%<extra></extra>",
                )
            )
        fig_major.update_layout(
            **{**CHART_LAYOUT_DEFAULTS, "margin": dict(l=10, r=10, t=10, b=10)},
            barmode="stack",
            legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02, font=dict(size=11)),
            yaxis=dict(gridcolor=GRID_COLOR, tickformat=",.0f", zeroline=False, rangemode="tozero"),
            xaxis=dict(type="category", gridcolor="rgba(0,0,0,0)"),
            hovermode="closest",
            height=340,
        )
        st.plotly_chart(fig_major, use_container_width=True)

    # 소분류 지출 Top 10 - 마찬가지로 독립된 연도 선택
    minor_title_col, minor_year_col = st.columns([3, 1])
    minor_title_col.subheader("소분류 지출 Top 10")
    if "dash_minor_chart_year" not in st.session_state:
        st.session_state.dash_minor_chart_year = selected_year
    minor_chart_year = minor_year_col.selectbox(
        "연도",
        options=year_options,
        format_func=lambda y: f"{y}년",
        index=year_options.index(st.session_state.dash_minor_chart_year),
        key="dash_minor_year_select",
        label_visibility="collapsed",
    )
    st.session_state.dash_minor_chart_year = minor_chart_year
    minor_start_month = TREND_START_DATE.month if minor_chart_year == TREND_START_DATE.year else 1
    minor_months = [f"{minor_chart_year:04d}-{m:02d}" for m in range(minor_start_month, 13)]
    minor_x_labels = [f"{int(m[5:7])}월" for m in minor_months]
    minor_by_month_rows = expense_by_category_by_months(minor_months, exclude_majors=exclude_majors)
    top10_start = f"{minor_months[0]}-01"
    top10_end = _month_bounds(minor_months[-1])[1]
    top10 = expense_by_category_range(top10_start, top10_end, limit=10, exclude_majors=exclude_majors)

    if not top10:
        st.caption("이 기간에는 지출 내역이 없습니다.")
    else:
        by_month_minor = {
            (r["month"], r["major_category"], r["minor_category"]): r["amount"] for r in minor_by_month_rows
        }
        # 그 달에 표시되는 대분류 합계(대분류 지출 차트와 같은 분모)를 hover 비중(%) 계산에 쓴다.
        minor_by_month_major_totals: dict[str, int] = {}
        for r in minor_by_month_rows:
            minor_by_month_major_totals[r["month"]] = minor_by_month_major_totals.get(r["month"], 0) + r["amount"]
        # 같은 대분류에 속한 소분류가 여러 개면 대분류 색을 공유하되(고정 5색 팔레트를 벗어난
        # 임의 색을 새로 만들지 않기 위함) 투명도를 단계적으로 낮춰 서로 구분되게 한다.
        major_seen: dict[str, int] = {}
        OPACITY_STEPS = [1.0, 0.7, 0.45, 0.3]
        fig_minor = go.Figure()
        for r in top10:
            label = (
                r["major_category"] if not r["minor_category"] else f"{r['major_category']}>{r['minor_category']}"
            )
            idx = major_seen.get(r["major_category"], 0)
            major_seen[r["major_category"]] = idx + 1
            opacity = OPACITY_STEPS[min(idx, len(OPACITY_STEPS) - 1)]
            amounts = [by_month_minor.get((m, r["major_category"], r["minor_category"]), 0) for m in minor_months]
            pct = [
                (v / minor_by_month_major_totals[m] * 100) if minor_by_month_major_totals.get(m) else 0
                for v, m in zip(amounts, minor_months)
            ]
            fig_minor.add_trace(
                go.Bar(
                    x=minor_x_labels,
                    y=amounts,
                    name=label,
                    marker_color=MAJOR_CATEGORY_COLORS.get(r["major_category"], EXPENSE_COLOR),
                    opacity=opacity,
                    customdata=pct,
                    hovertemplate=f"{label} " + "%{y:,.0f} %{customdata:.0f}%<extra></extra>",
                )
            )
        fig_minor.update_layout(
            **{**CHART_LAYOUT_DEFAULTS, "margin": dict(l=10, r=10, t=10, b=10)},
            barmode="stack",
            legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02, font=dict(size=10)),
            yaxis=dict(gridcolor=GRID_COLOR, tickformat=",.0f", zeroline=False, rangemode="tozero"),
            xaxis=dict(type="category", gridcolor="rgba(0,0,0,0)"),
            hovermode="closest",
            height=340,
        )
        st.plotly_chart(fig_minor, use_container_width=True)

st.divider()

# ============================================================
# 카테고리별 상세 (천원 단위, 중앙정렬, 합계행) - 자체 월 이동 화살표
# ============================================================
with st.container(border=True, key="dash_card_detail"):
    if "dash_detail_year" not in st.session_state:
        st.session_state.dash_detail_year = today.year
    if "dash_detail_month" not in st.session_state:
        st.session_state.dash_detail_month = today.month

    detail_title_col, detail_year_col, detail_month_col = st.columns([3, 1, 1])
    detail_title_col.subheader("카테고리별 상세")

    detail_year_default = (
        st.session_state.dash_detail_year if st.session_state.dash_detail_year in year_options else year_options[-1]
    )
    detail_year = detail_year_col.selectbox(
        "연도",
        options=year_options,
        format_func=lambda y: f"{y}년",
        index=year_options.index(detail_year_default),
        key="dash_detail_year_select",
        label_visibility="collapsed",
    )
    st.session_state.dash_detail_year = detail_year

    detail_month_options = list(range(TREND_START_DATE.month, 13)) if detail_year == TREND_START_DATE.year else list(range(1, 13))
    detail_month_default = (
        st.session_state.dash_detail_month
        if st.session_state.dash_detail_month in detail_month_options
        else detail_month_options[-1]
    )
    detail_month = detail_month_col.selectbox(
        "월",
        options=detail_month_options,
        format_func=lambda m: f"{m}월",
        index=detail_month_options.index(detail_month_default),
        key="dash_detail_month_select",
        label_visibility="collapsed",
    )
    st.session_state.dash_detail_month = detail_month

    detail_period_month = f"{detail_year:04d}-{detail_month:02d}"
    period_start, period_end = _month_bounds(detail_period_month)
    detail_rows = expense_by_category_range(period_start, period_end, exclude_majors=exclude_majors)

    filter_note = f"제외 중: {', '.join(exclude_majors)}" if exclude_majors else "전체 대분류 포함 중"
    st.caption(f"{detail_period_month} 기준 · '분석에서 제외할 대분류' 필터가 이 표에도 적용됩니다 ({filter_note})")

    if detail_rows:
        st.markdown(_detail_table_html(detail_rows), unsafe_allow_html=True)
    else:
        st.caption("이 기간에는 지출 내역이 없습니다.")

st.divider()

# ============================================================
# 날짜별 지출 (캘린더, 자체 월 이동)
# ============================================================
if "dash_calendar_month" not in st.session_state:
    st.session_state.dash_calendar_month = today.strftime("%Y-%m")

with st.container(border=True, key="dash_card_calendar"):
    cal_prev, cal_title, cal_next = st.columns([1, 6, 1])
    if cal_prev.button("◀", key="cal_prev_btn"):
        st.session_state.dash_calendar_month = _shift_month(st.session_state.dash_calendar_month, -1)
        st.rerun()
    cal_title.markdown(
        f"<h4 style='text-align:center;'>{st.session_state.dash_calendar_month} 날짜별 지출</h4>",
        unsafe_allow_html=True,
    )
    if cal_next.button("▶", key="cal_next_btn"):
        st.session_state.dash_calendar_month = _shift_month(st.session_state.dash_calendar_month, 1)
        st.rerun()

    cal_start, cal_end = _month_bounds(st.session_state.dash_calendar_month)
    cal_daily = daily_expense_in_range(cal_start, cal_end)
    st.markdown(_calendar_html(st.session_state.dash_calendar_month, cal_daily), unsafe_allow_html=True)
