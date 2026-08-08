import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

RECEIPTS_IMAGE_DIR = DATA_DIR / "receipt_images"
RECEIPTS_IMAGE_DIR.mkdir(exist_ok=True)

DB_PATH = os.getenv("DB_PATH", str(DATA_DIR / "ledger.db"))

# 3단계(OCR)/4단계(AI 분류)부터 사용. 키가 없으면 로컬/스텁 모드로 동작해야 한다.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# 6단계부터 사용
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", "http://localhost:8501")
# 카카오 콘솔에서 "카카오 로그인" 클라이언트 시크릿을 활성화한 경우에만 필요 (없으면 None -> 토큰 요청에서 생략)
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")
