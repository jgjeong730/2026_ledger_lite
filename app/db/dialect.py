"""SQLite/Postgres 양쪽에서 동작해야 하는 날짜 관련 SQL 조각을 백엔드별로 생성한다.

서비스 코드는 하드코딩된 strftime() 대신 이 함수들을 써서 SQL 텍스트를 조립한다.
백엔드 판정은 app.db.connection.SUPABASE_DB_URL을 참조한다 (테스트에서 그 값을
monkeypatch하면 이 모듈도 함께 SQLite 경로로 동작한다).
"""

from app.db import connection as db_connection


def is_postgres() -> bool:
    return bool(db_connection.SUPABASE_DB_URL)


def year_month_expr(column: str) -> str:
    """column(YYYY-MM-DD 텍스트)을 'YYYY-MM' 텍스트로 변환하는 SQL 표현식."""
    if is_postgres():
        return f"to_char({column}::date, 'YYYY-MM')"
    return f"strftime('%Y-%m', {column})"


def week_start_expr(column: str) -> str:
    """column이 속한 주의 월요일을 'YYYY-MM-DD' 텍스트로 반환하는 SQL 표현식.

    strftime('%w')/EXTRACT(DOW)는 둘 다 0=일요일..6=토요일이므로,
    (요일+6)%7 만큼 빼면 그 주의 월요일이 된다 (두 백엔드 공통 공식).
    """
    if is_postgres():
        # psycopg는 파라미터 바인딩에 %s(pyformat) 스타일을 쓰므로, SQL 안의 리터럴
        # '%'(나머지 연산자)는 반드시 '%%'로 두 번 써야 플레이스홀더로 오인되지 않는다.
        return (
            f"to_char({column}::date - "
            f"(((EXTRACT(DOW FROM {column}::date)::int + 6) %% 7) * INTERVAL '1 day'), "
            "'YYYY-MM-DD')"
        )
    return (
        f"date({column}, '-' || ((CAST(strftime('%w', {column}) AS INTEGER) + 6) % 7) || ' days')"
    )


def now_text_expr() -> str:
    """현재 시각을 'YYYY-MM-DDTHH:MM:SS' 텍스트로 반환하는 SQL 표현식 (Asia/Seoul 기준)."""
    if is_postgres():
        return "to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD\"T\"HH24:MI:SS')"
    return "strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')"


def current_year_month_expr() -> str:
    """현재 연월을 'YYYY-MM' 텍스트로 반환하는 SQL 표현식 (Asia/Seoul 기준)."""
    if is_postgres():
        return "to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM')"
    return "strftime('%Y-%m', 'now', 'localtime')"
