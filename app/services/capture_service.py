"""captures 테이블 및 영수증 이미지 파일 저장 담당 (수집 계층)."""

import uuid
from pathlib import Path

from app.config import RECEIPTS_IMAGE_DIR
from app.db.connection import get_connection


def find_existing_text_capture(source_type: str, raw_text: str) -> int | None:
    """동일 원문이 이미 입력되어 있는지 확인한다 (중복 붙여넣기 방지).

    이전에 파싱 실패(status='failed')했던 캡처는 제외한다 - 그렇지 않으면 파서를
    고친 뒤 같은 원문을 다시 붙여넣어도 "중복"으로 오인해 재시도가 막힌다."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM captures WHERE source_type = ? AND raw_text = ? AND status != 'failed'",
            (source_type, raw_text),
        ).fetchone()
    finally:
        conn.close()
    return row["id"] if row else None


def create_text_capture(source_type: str, raw_text: str, status: str = "pending") -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO captures (source_type, raw_text, status) VALUES (?, ?, ?)",
            (source_type, raw_text, status),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def save_receipt_image(file_bytes: bytes, original_filename: str) -> str:
    """업로드된 영수증 이미지를 data/receipt_images/에 저장하고 경로를 반환한다."""
    suffix = Path(original_filename).suffix or ".jpg"
    unique_name = f"{uuid.uuid4().hex}{suffix}"
    dest = RECEIPTS_IMAGE_DIR / unique_name
    dest.write_bytes(file_bytes)
    return str(dest)


def create_image_capture(image_path: str, status: str = "pending") -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO captures (source_type, image_path, status) VALUES ('receipt_image', ?, ?)",
            (image_path, status),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def mark_capture_status(capture_id: int, status: str, error_message: str | None = None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE captures SET status = ?, error_message = ? WHERE id = ?",
            (status, error_message, capture_id),
        )
        conn.commit()
    finally:
        conn.close()
