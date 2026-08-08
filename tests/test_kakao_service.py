"""kakao_service의 오프라인 테스트. 실제 카카오 서버 호출은 하지 않고 requests.post를 모킹한다."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services import kakao_service  # noqa: E402


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


@pytest.fixture()
def token_file(tmp_path, monkeypatch):
    path = tmp_path / "kakao_token.json"
    monkeypatch.setattr(kakao_service, "TOKEN_FILE", path)
    return path


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(config, "KAKAO_REST_API_KEY", "test-rest-api-key")
    monkeypatch.setattr(config, "KAKAO_REDIRECT_URI", "http://localhost:8501")


@pytest.fixture()
def not_configured(monkeypatch):
    monkeypatch.setattr(config, "KAKAO_REST_API_KEY", None)


def test_is_configured_reflects_key(configured):
    assert kakao_service.is_configured() is True


def test_is_configured_false_without_key(not_configured):
    assert kakao_service.is_configured() is False


def test_build_authorize_url_raises_when_not_configured(not_configured):
    with pytest.raises(kakao_service.KakaoNotConfiguredError):
        kakao_service.build_authorize_url()


def test_build_authorize_url_contains_required_params(configured):
    url = kakao_service.build_authorize_url()
    assert url.startswith("https://kauth.kakao.com/oauth/authorize?")
    assert "client_id=test-rest-api-key" in url
    assert "redirect_uri=http://localhost:8501" in url
    assert "response_type=code" in url
    assert "scope=profile_nickname,talk_message" in url


def test_exchange_code_for_token_saves_tokens(configured, token_file, monkeypatch):
    def fake_post(url, data=None, headers=None, timeout=None):
        assert url == "https://kauth.kakao.com/oauth/token"
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "abc123"
        return FakeResponse(200, {"access_token": "AT1", "refresh_token": "RT1", "expires_in": 21600, "refresh_token_expires_in": 5184000})

    monkeypatch.setattr(kakao_service.requests, "post", fake_post)

    kakao_service.exchange_code_for_token("abc123")

    tokens = kakao_service.load_tokens()
    assert tokens["access_token"] == "AT1"
    assert tokens["refresh_token"] == "RT1"
    assert kakao_service.is_logged_in() is True


def test_exchange_code_for_token_raises_on_error_response(configured, token_file, monkeypatch):
    monkeypatch.setattr(kakao_service.requests, "post", lambda *a, **k: FakeResponse(400, text="bad code"))
    with pytest.raises(kakao_service.KakaoRequestError):
        kakao_service.exchange_code_for_token("bad-code")
    assert kakao_service.load_tokens() is None


def test_get_valid_access_token_raises_when_not_logged_in(configured, token_file):
    with pytest.raises(kakao_service.KakaoAuthError):
        kakao_service.get_valid_access_token()


def test_get_valid_access_token_returns_cached_token_when_not_expired(configured, token_file):
    token_file.write_text(
        json.dumps({"access_token": "AT1", "access_token_expires_at": time.time() + 3600, "refresh_token": "RT1"}),
        encoding="utf-8",
    )
    assert kakao_service.get_valid_access_token() == "AT1"


def test_get_valid_access_token_refreshes_when_expired(configured, token_file, monkeypatch):
    token_file.write_text(
        json.dumps({"access_token": "OLD", "access_token_expires_at": time.time() - 10, "refresh_token": "RT1"}),
        encoding="utf-8",
    )

    def fake_post(url, data=None, headers=None, timeout=None):
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "RT1"
        return FakeResponse(200, {"access_token": "NEW", "expires_in": 21600})

    monkeypatch.setattr(kakao_service.requests, "post", fake_post)

    token = kakao_service.get_valid_access_token()
    assert token == "NEW"
    # 갱신 응답에 refresh_token이 없으면 기존 값을 그대로 유지해야 한다
    assert kakao_service.load_tokens()["refresh_token"] == "RT1"


def test_get_valid_access_token_raises_when_refresh_fails(configured, token_file, monkeypatch):
    token_file.write_text(
        json.dumps({"access_token": "OLD", "access_token_expires_at": time.time() - 10, "refresh_token": "RT1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(kakao_service.requests, "post", lambda *a, **k: FakeResponse(400, text="expired"))

    with pytest.raises(kakao_service.KakaoAuthError):
        kakao_service.get_valid_access_token()


def test_send_memo_to_me_success(configured, token_file, monkeypatch):
    token_file.write_text(
        json.dumps({"access_token": "AT1", "access_token_expires_at": time.time() + 3600, "refresh_token": "RT1"}),
        encoding="utf-8",
    )

    captured = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = data
        return FakeResponse(200, {"result_code": 0})

    monkeypatch.setattr(kakao_service.requests, "post", fake_post)

    kakao_service.send_memo_to_me("테스트 메시지")

    assert captured["url"] == "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    assert captured["headers"]["Authorization"] == "Bearer AT1"
    template = json.loads(captured["data"]["template_object"])
    assert template["object_type"] == "text"
    assert template["text"] == "테스트 메시지"


def test_send_memo_to_me_raises_on_failure(configured, token_file, monkeypatch):
    token_file.write_text(
        json.dumps({"access_token": "AT1", "access_token_expires_at": time.time() + 3600, "refresh_token": "RT1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(kakao_service.requests, "post", lambda *a, **k: FakeResponse(500, text="server error"))

    with pytest.raises(kakao_service.KakaoRequestError):
        kakao_service.send_memo_to_me("실패해야 함")


def test_logout_removes_token_file(configured, token_file):
    token_file.write_text(json.dumps({"access_token": "AT1", "access_token_expires_at": time.time() + 3600}), encoding="utf-8")
    assert kakao_service.is_logged_in() is True
    kakao_service.logout()
    assert kakao_service.is_logged_in() is False
