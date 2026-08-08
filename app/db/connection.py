"""SQLite 연결/초기화.

지금은 sqlite3 표준 라이브러리를 직접 사용한다. 나중에 Supabase 등으로 옮길 때를 대비해
DB 접근은 이 모듈(get_connection/init_db)을 통해서만 하도록 나머지 코드에서 지켜야 한다.
"""

import sqlite3
from pathlib import Path

from app.config import BASE_DIR, DB_PATH

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _resolve_db_path() -> str:
    path = Path(DB_PATH)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_resolve_db_path())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """schema.sql을 실행해 테이블이 없으면 생성한다 (있으면 그대로 둠, 데이터 보존)."""
    conn = get_connection()
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()
