"""카카오 로그인(OAuth) + 카카오톡 '나에게 보내기' 메시지 전송.

PROJECT_BRIEF 3절: 카카오 개발자 앱 등록 완료 (REST API 키, Redirect URI, 동의항목
profile_nickname/talk_message 설정 완료). 별도 사용권한 신청이 필요 없는
POST /v2/api/talk/memo/default/send(나에게 보내기)만 사용한다.

1인용 로컬 앱이므로 OAuth 토큰은 DB가 아니라 data/kakao_token.json에 그대로 저장한다
(다른 로컬 상태 파일들과 동일한 수준의 취급 - .gitignore에 등록되어 있어야 한다).
KAKAO_REST_API_KEY가 없으면 예외를 던지고, 호출부(카카오 알림 페이지)가 설정 안내로 유도한다.
"""

import json
import time
from pathlib import Path

import requests

from app import config

_AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
_SCOPE = "profile_nickname,talk_message"

TOKEN_FILE: Path = config.DATA_DIR / "kakao_token.json"

# 토큰 만료 판정에 여유를 두어, 만료 직전 순간에 API를 호출해 실패하는 것을 방지한다.
_EXPIRY_MARGIN_SECONDS = 60


class KakaoNotConfiguredError(RuntimeError):
    """KAKAO_REST_API_KEY가 설정되지 않았을 때."""


class KakaoAuthError(RuntimeError):
    """로그인이 안 되어 있거나 토큰 갱신에 실패했을 때 (재로그인 필요)."""


class KakaoRequestError(RuntimeError):
    """카카오 API 호출은 됐지만 실패 응답을 받았을 때."""


def is_configured() -> bool:
    return bool(config.KAKAO_REST_API_KEY)


def _with_client_secret(data: dict) -> dict:
    """카카오 콘솔에서 '카카오 로그인' 클라이언트 시크릿을 활성화한 경우 토큰 요청에 함께 실어 보낸다.
    비활성화 상태(KAKAO_CLIENT_SECRET 미설정)면 그냥 원래 데이터를 반환한다."""
    if config.KAKAO_CLIENT_SECRET:
        data["client_secret"] = config.KAKAO_CLIENT_SECRET
    return data


def _require_configured() -> None:
    if not is_configured():
        raise KakaoNotConfiguredError(
            "KAKAO_REST_API_KEY가 설정되지 않았습니다. .env에 카카오 REST API 키를 추가해주세요."
        )


def build_authorize_url() -> str:
    """사용자를 카카오 로그인 동의 화면으로 보낼 URL. 콜백은 KAKAO_REDIRECT_URI(기본 앱 홈)로 온다."""
    _require_configured()
    params = (
        f"client_id={config.KAKAO_REST_API_KEY}"
        f"&redirect_uri={config.KAKAO_REDIRECT_URI}"
        "&response_type=code"
        f"&scope={_SCOPE}"
    )
    return f"{_AUTHORIZE_URL}?{params}"


def _save_tokens(token_response: dict) -> None:
    now = time.time()
    data = {
        "access_token": token_response["access_token"],
        "access_token_expires_at": now + token_response["expires_in"],
        "refresh_token": token_response.get("refresh_token"),
    }
    # 카카오는 refresh_token 만료가 임박했을 때만 새 refresh_token을 내려준다 - 없으면 기존 값 유지
    existing = load_tokens()
    if "refresh_token_expires_in" in token_response:
        data["refresh_token_expires_at"] = now + token_response["refresh_token_expires_in"]
    elif existing and "refresh_token_expires_at" in existing:
        data["refresh_token_expires_at"] = existing["refresh_token_expires_at"]
    if data["refresh_token"] is None and existing:
        data["refresh_token"] = existing.get("refresh_token")
        data.setdefault("refresh_token_expires_at", existing.get("refresh_token_expires_at"))

    TOKEN_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load_tokens() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def logout() -> None:
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


def exchange_code_for_token(code: str) -> None:
    """로그인 콜백에서 받은 authorization code를 access/refresh token으로 교환해 저장한다."""
    _require_configured()
    response = requests.post(
        _TOKEN_URL,
        data=_with_client_secret({
            "grant_type": "authorization_code",
            "client_id": config.KAKAO_REST_API_KEY,
            "redirect_uri": config.KAKAO_REDIRECT_URI,
            "code": code,
        }),
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        timeout=10,
    )
    if response.status_code != 200:
        raise KakaoRequestError(f"토큰 교환 실패 ({response.status_code}): {response.text}")
    _save_tokens(response.json())


def _refresh_access_token(refresh_token: str) -> None:
    response = requests.post(
        _TOKEN_URL,
        data=_with_client_secret({
            "grant_type": "refresh_token",
            "client_id": config.KAKAO_REST_API_KEY,
            "refresh_token": refresh_token,
        }),
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        timeout=10,
    )
    if response.status_code != 200:
        raise KakaoAuthError(f"토큰 갱신 실패 ({response.status_code}): {response.text} - 다시 로그인해주세요.")
    _save_tokens(response.json())


def is_logged_in() -> bool:
    return load_tokens() is not None


def get_valid_access_token() -> str:
    """유효한 access_token을 반환한다. 만료됐으면 자동 갱신을 시도하고, 그마저 안 되면 재로그인을 요구한다."""
    _require_configured()
    tokens = load_tokens()
    if tokens is None:
        raise KakaoAuthError("카카오 로그인이 필요합니다.")

    if time.time() < tokens["access_token_expires_at"] - _EXPIRY_MARGIN_SECONDS:
        return tokens["access_token"]

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise KakaoAuthError("로그인이 만료되었습니다. 다시 로그인해주세요.")

    _refresh_access_token(refresh_token)
    return load_tokens()["access_token"]


def send_memo_to_me(text: str) -> None:
    """카카오톡 '나에게 보내기'로 텍스트 메시지를 전송한다."""
    access_token = get_valid_access_token()
    template_object = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": config.KAKAO_REDIRECT_URI,
            "mobile_web_url": config.KAKAO_REDIRECT_URI,
        },
    }
    response = requests.post(
        _MEMO_SEND_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"template_object": json.dumps(template_object, ensure_ascii=False)},
        timeout=10,
    )
    if response.status_code != 200:
        raise KakaoRequestError(f"메시지 전송 실패 ({response.status_code}): {response.text}")
