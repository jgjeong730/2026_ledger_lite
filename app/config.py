import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get_secret(key: str, default: str | None = None) -> str | None:
    """환경변수(.env, OS env)를 우선 확인하고, 없으면 Streamlit Cloud의 st.secrets를 확인한다.
    로컬 개발/테스트처럼 Streamlit 런타임/시크릿 파일이 없는 환경에서는 조용히 default로 넘어간다."""
    value = os.getenv(key)
    if value:
        return value
    try:
        import streamlit as st

        return st.secrets.get(key, default)
    except Exception:
        return default


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

RECEIPTS_IMAGE_DIR = DATA_DIR / "receipt_images"
RECEIPTS_IMAGE_DIR.mkdir(exist_ok=True)

DB_PATH = _get_secret("DB_PATH", str(DATA_DIR / "ledger.db"))

# 설정되면 SQLite 대신 이 Postgres(Supabase)로 연결한다 (배포 환경의 영구 저장소).
# 비워두면(None) 로컬 SQLite 파일을 사용한다 (로컬 개발/테스트 기본값).
SUPABASE_DB_URL = _get_secret("SUPABASE_DB_URL")

# 3단계(OCR)/4단계(AI 분류)부터 사용. 키가 없으면 로컬/스텁 모드로 동작해야 한다.
ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")

# 6단계부터 사용
KAKAO_REST_API_KEY = _get_secret("KAKAO_REST_API_KEY")
KAKAO_REDIRECT_URI = _get_secret("KAKAO_REDIRECT_URI", "http://localhost:8501")
# 카카오 콘솔에서 "카카오 로그인" 클라이언트 시크릿을 활성화한 경우에만 필요 (없으면 None -> 토큰 요청에서 생략)
KAKAO_CLIENT_SECRET = _get_secret("KAKAO_CLIENT_SECRET")

# 설정하면 전체 앱이 비밀번호 게이트로 보호된다. 비워두면(None) 게이트 없이 그대로 접근 가능
# (로컬 개발 기본값). 공개 URL로 배포할 때는 반드시 설정할 것.
APP_PASSWORD = _get_secret("APP_PASSWORD")
