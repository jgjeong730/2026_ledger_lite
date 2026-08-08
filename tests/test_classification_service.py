"""classification_service의 오프라인 테스트. 실제 Claude API 호출은 하지 않는다 (test_vision_service.py 참고)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services import classification_service  # noqa: E402


@pytest.fixture()
def no_api_key(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)


@pytest.fixture()
def with_api_key(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test-fake-key")


def test_is_configured_reflects_api_key(no_api_key):
    assert classification_service.is_configured() is False


def test_is_configured_true_when_key_present(with_api_key):
    assert classification_service.is_configured() is True


def test_classify_merchant_raises_when_not_configured(no_api_key):
    with pytest.raises(classification_service.ClassificationNotConfiguredError):
        classification_service.classify_merchant(merchant_name="대신주유소", amount=100000)
