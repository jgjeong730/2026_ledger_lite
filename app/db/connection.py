"""DB 연결/초기화. SUPABASE_DB_URL이 설정되어 있으면 Postgres(Supabase)를,
없으면 로컬 SQLite 파일을 사용한다.

나머지 코드는 이 모듈(get_connection/init_db)을 통해서만 DB에 접근하고, 항상
"?" 플레이스홀더 + sqlite3.Row 스타일(딕셔너리 키 접근)의 SQL을 쓴다. Postgres로
연결됐을 때는 _PGConnection/_PGCursor가 그 스타일을 그대로 흉내내 서비스 코드를
백엔드에 따라 분기하지 않아도 되게 한다 (날짜 함수처럼 SQL 텍스트 자체가 다른
경우는 app/db/dialect.py를 사용).
"""

import re
import sqlite3
from pathlib import Path

from app.config import BASE_DIR, DB_PATH, SUPABASE_DB_URL

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SCHEMA_POSTGRES_PATH = Path(__file__).parent / "schema_postgres.sql"

_PLACEHOLDER_RE = re.compile(r"\?")
_INSERT_RE = re.compile(r"^\s*INSERT\b", re.IGNORECASE)


def _resolve_db_path() -> str:
    path = Path(DB_PATH)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _prepare_pg_sql(sql: str) -> tuple[str, bool]:
    """"?" 플레이스홀더를 "%s"로 바꾸고, id 반환이 필요한 INSERT면 RETURNING id를 붙인다."""
    prepped = _PLACEHOLDER_RE.sub("%s", sql)
    wants_id = bool(_INSERT_RE.match(prepped)) and "RETURNING" not in prepped.upper()
    if wants_id:
        prepped = prepped.rstrip().rstrip(";") + " RETURNING id"
    return prepped, wants_id


class _PGCursor:
    """psycopg Cursor는 __slots__ 때문에 임의 속성(lastrowid)을 못 붙이므로 감싼다.
    fetchone/fetchall/rowcount 등은 그대로 실제 커서에 위임한다."""

    def __init__(self, raw_cursor):
        self._cur = raw_cursor
        self.lastrowid = None

    def __getattr__(self, name):
        return getattr(self._cur, name)

    def __iter__(self):
        return iter(self._cur)


class _PGConnection:
    """psycopg Connection을 sqlite3.Connection과 같은 방식으로 호출할 수 있게 감싼다."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql: str, params=()):
        from psycopg.rows import dict_row

        cur = _PGCursor(self._conn.cursor(row_factory=dict_row))
        prepped, wants_id = _prepare_pg_sql(sql)
        cur.execute(prepped, params)
        if wants_id:
            row = cur.fetchone()
            cur.lastrowid = row["id"] if row else None
        return cur

    def executemany(self, sql: str, seq_of_params):
        from psycopg.rows import dict_row

        cur = _PGCursor(self._conn.cursor(row_factory=dict_row))
        prepped, _ = _prepare_pg_sql(sql)
        cur.executemany(prepped, seq_of_params)
        return cur

    def executescript(self, sql: str):
        cur = _PGCursor(self._conn.cursor())
        cur.execute(sql)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_connection():
    if SUPABASE_DB_URL:
        import psycopg

        return _PGConnection(psycopg.connect(SUPABASE_DB_URL))

    conn = sqlite3.connect(_resolve_db_path())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """스키마를 실행해 테이블이 없으면 생성한다 (있으면 그대로 둠, 데이터 보존)."""
    schema_path = SCHEMA_POSTGRES_PATH if SUPABASE_DB_URL else SCHEMA_PATH
    conn = get_connection()
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()
