"""vision_service / receipt_service의 OCR 연동 오프라인 테스트.

실제 Claude API 호출은 네트워크/과금이 필요해 테스트하지 않는다. 여기서는 API 키가 없을 때
(로컬 모드) 앱이 예외 대신 명확한 폴백 상태를 반환하는지, 그리고 카테고리 enum 빌더가 DB의
categories 테이블과 일치하는지를 검증한다.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.db import connection as db_connection  # noqa: E402
from app.db.seed_categories import CATEGORY_SEED, seed_categories  # noqa: E402
from app.services import vision_service  # noqa: E402
from app.services.category_service import category_enum_options  # noqa: E402
from app.services.receipt_service import ingest_receipt_image_ocr  # noqa: E402


@pytest.fixture()
def db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_ledger.db"
    monkeypatch.setattr(db_connection, "BASE_DIR", tmp_path)
    monkeypatch.setattr(db_connection, "DB_PATH", str(db_file))
    monkeypatch.setattr(db_connection, "SUPABASE_DB_URL", None)
    db_connection.init_db()
    seed_categories()
    yield db_connection
    db_connection.get_connection().close()


@pytest.fixture()
def no_api_key(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)


@pytest.fixture()
def with_api_key(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test-fake-key")


def test_is_configured_reflects_api_key(no_api_key):
    assert vision_service.is_configured() is False


def test_is_configured_true_when_key_present(with_api_key):
    assert vision_service.is_configured() is True


def test_analyze_receipt_image_raises_when_not_configured(no_api_key):
    with pytest.raises(vision_service.VisionNotConfiguredError):
        vision_service.analyze_receipt_image(b"fake-image-bytes", "receipt.jpg")


def test_category_enum_matches_expense_categories(db):
    enum_values = category_enum_options()
    expense_minor_count = sum(
        1 for entry_type, major, minor, is_system, _ in CATEGORY_SEED if entry_type == "expense" and not is_system
    )
    # 시스템 카테고리(미분류·확인필요) 대신 "미분류" 한 개만 추가된다
    assert len(enum_values) == expense_minor_count + 1
    assert "미분류" in enum_values
    assert "라이프스타일비>소셜/네트워킹" in enum_values
    assert "고정비>통신비" in enum_values


def test_ingest_receipt_image_ocr_falls_back_when_not_configured(db, no_api_key, tmp_path):
    image_path = tmp_path / "fake_receipt.jpg"
    image_path.write_bytes(b"not-a-real-image")

    result = ingest_receipt_image_ocr(
        image_path=str(image_path),
        image_bytes=b"not-a-real-image",
        filename="fake_receipt.jpg",
    )

    assert result["status"] == "ocr_unavailable"
    assert "error" in result

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT status, error_message FROM captures WHERE id = ?", (result["capture_id"],)
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "failed"
    assert row["error_message"]
