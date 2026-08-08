"""ocr_results / receipts / classifications / merchant_rules 담당 (분석 계층 + 학습 규칙).

이 모듈이 4개 입력 채널(카드문자/카카오페이/영수증/은행이체)을 각각
capture -> ocr_result -> receipt -> classification 흐름으로 연결하는 지점이다.
AI 분류(4단계)가 아직 없으므로, 이번 단계의 기본 분류 우선순위는:
    1) merchant_rules에 사용자가 학습시킨 규칙이 있으면 그것을 적용 (classified_by='rule')
    2) 카카오페이는 항상 라이프스타일비>소셜/네트워킹 고정 배정 (classified_by='rule')
    3) 그 외에는 '미분류·확인필요'로 두고 사용자 확인을 기다림 (classified_by='default')
"""

import json
import re
from dataclasses import asdict

from app.db.connection import get_connection
from app.parsers.card_sms_parser import CardSmsParseError, parse_card_sms
from app.parsers.kakaopay_parser import KakaopayParseError, parse_kakaopay
from app.services.capture_service import (
    create_image_capture,
    create_text_capture,
    find_existing_text_capture,
    mark_capture_status,
)
from app.services.category_service import (
    get_kakaopay_default_category_id,
    get_uncategorized_category_id,
)

# ============================================================
# ocr_results / receipts / classifications 저수준 CRUD
# ============================================================


def create_ocr_result(
    *,
    capture_id: int,
    engine: str,
    merchant_name: str | None,
    amount: int | None,
    txn_date: str | None,
    txn_time: str | None,
    flow_direction: str | None,
    confidence: float | None = None,
    status: str = "success",
    raw_output: str | None = None,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO ocr_results
                (capture_id, engine, raw_output, merchant_name, amount, txn_date, txn_time,
                 flow_direction, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capture_id,
                engine,
                raw_output,
                merchant_name,
                amount,
                txn_date,
                txn_time,
                flow_direction,
                confidence,
                status,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def create_receipt(
    *,
    capture_id: int | None,
    ocr_result_id: int | None,
    entry_type: str,
    source_type: str,
    flow_direction: str,
    merchant_name: str | None,
    amount: int,
    transaction_date: str,
    transaction_time: str | None = None,
    payment_method: str | None = None,
    memo: str | None = None,
    review_status: str = "needs_review",
    is_manual_entry: int = 0,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO receipts
                (capture_id, ocr_result_id, entry_type, source_type, flow_direction,
                 merchant_name, amount, transaction_date, transaction_time,
                 payment_method, memo, review_status, is_manual_entry)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capture_id,
                ocr_result_id,
                entry_type,
                source_type,
                flow_direction,
                merchant_name,
                amount,
                transaction_date,
                transaction_time,
                payment_method,
                memo,
                review_status,
                is_manual_entry,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def classify_receipt(
    receipt_id: int,
    category_id: int | None,
    classified_by: str,
    *,
    confidence: float | None = None,
    rule_id: int | None = None,
    note: str | None = None,
) -> int:
    """receipt의 현재 분류를 교체한다 (기존 is_current=1 행은 0으로, 새 행을 1로)."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE classifications SET is_current = 0 WHERE receipt_id = ? AND is_current = 1",
            (receipt_id,),
        )
        cur = conn.execute(
            """
            INSERT INTO classifications
                (receipt_id, category_id, classified_by, rule_id, confidence, note, is_current)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (receipt_id, category_id, classified_by, rule_id, confidence, note),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ============================================================
# merchant_rules: 사용자가 재분류하면 학습되어 다음 자동분류에 반영
# ============================================================


def _rule_matches(rule, merchant_name: str) -> bool:
    pattern, match_type = rule["pattern"], rule["match_type"]
    if match_type == "exact":
        return merchant_name == pattern
    if match_type == "contains":
        return pattern in merchant_name
    if match_type == "regex":
        return re.search(pattern, merchant_name) is not None
    return False


def find_matching_rule(merchant_name: str | None, source_type: str):
    if not merchant_name:
        return None
    conn = get_connection()
    try:
        rules = conn.execute(
            """
            SELECT * FROM merchant_rules
            WHERE is_active = 1 AND (source_type IS NULL OR source_type = ?)
            ORDER BY priority ASC, id ASC
            """,
            (source_type,),
        ).fetchall()
    finally:
        conn.close()
    for rule in rules:
        if _rule_matches(rule, merchant_name):
            return rule
    return None


def learn_rule_from_correction(merchant_name: str, source_type: str, category_id: int) -> int:
    """사용자의 재분류를 가맹점명 기준 규칙으로 저장(이미 있으면 카테고리만 갱신)한다."""
    conn = get_connection()
    try:
        existing = conn.execute(
            """
            SELECT id FROM merchant_rules
            WHERE match_type = 'exact' AND pattern = ? AND source_type = ? AND created_by = 'user'
            """,
            (merchant_name, source_type),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE merchant_rules
                SET category_id = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
                WHERE id = ?
                """,
                (category_id, existing["id"]),
            )
            rule_id = existing["id"]
        else:
            cur = conn.execute(
                """
                INSERT INTO merchant_rules (match_type, pattern, source_type, category_id, priority, created_by)
                VALUES ('exact', ?, ?, ?, 50, 'user')
                """,
                (merchant_name, source_type, category_id),
            )
            rule_id = cur.lastrowid
        conn.commit()
        return rule_id
    finally:
        conn.close()


def reclassify_and_learn(receipt_id: int, category_id: int, merchant_name: str | None, source_type: str) -> None:
    """거래내역 화면에서 사용자가 카테고리를 직접 고칠 때 사용. merchant_rules에도 반영된다."""
    rule_id = None
    if merchant_name and source_type in ("card_sms", "receipt_image"):
        rule_id = learn_rule_from_correction(merchant_name, source_type, category_id)

    classify_receipt(receipt_id, category_id, "user", rule_id=rule_id, note="사용자 재분류")

    conn = get_connection()
    try:
        conn.execute("UPDATE receipts SET review_status = 'confirmed' WHERE id = ?", (receipt_id,))
        conn.commit()
    finally:
        conn.close()


# ============================================================
# 채널별 진입점: capture -> ocr_result -> receipt -> classification
# ============================================================


def ingest_card_sms(raw_text: str) -> dict:
    existing_id = find_existing_text_capture("card_sms", raw_text)
    if existing_id:
        return {"status": "duplicate", "capture_id": existing_id}

    try:
        parsed = parse_card_sms(raw_text)
    except CardSmsParseError as e:
        capture_id = create_text_capture("card_sms", raw_text, status="failed")
        mark_capture_status(capture_id, "failed", str(e))
        return {"status": "parse_failed", "capture_id": capture_id, "error": str(e)}

    capture_id = create_text_capture("card_sms", raw_text, status="parsed")
    ocr_result_id = create_ocr_result(
        capture_id=capture_id,
        engine="regex_card_sms",
        merchant_name=parsed.merchant,
        amount=parsed.amount,
        txn_date=parsed.txn_date,
        txn_time=parsed.txn_time,
        flow_direction="outflow",
        confidence=1.0,
        raw_output=json.dumps(asdict(parsed), ensure_ascii=False),
    )

    rule = find_matching_rule(parsed.merchant, "card_sms")
    if rule:
        category_id, classified_by, rule_id = rule["category_id"], "rule", rule["id"]
        note = f"학습된 규칙 매칭: '{rule['pattern']}'"
    else:
        category_id, classified_by, rule_id = get_uncategorized_category_id(), "default", None
        note = "가맹점 규칙 없음 - 기본 미분류 (4단계 AI 분류 예정)"

    receipt_id = create_receipt(
        capture_id=capture_id,
        ocr_result_id=ocr_result_id,
        entry_type="expense",
        source_type="card_sms",
        flow_direction="outflow",
        merchant_name=parsed.merchant,
        amount=parsed.amount,
        transaction_date=parsed.txn_date,
        transaction_time=parsed.txn_time,
        payment_method=parsed.company,
        review_status="needs_review",
    )
    classify_receipt(receipt_id, category_id, classified_by, rule_id=rule_id, note=note)

    return {
        "status": "ok",
        "receipt_id": receipt_id,
        "merchant": parsed.merchant,
        "amount": parsed.amount,
        "txn_date": parsed.txn_date,
        "classified_by": classified_by,
    }


def ingest_kakaopay(raw_text: str) -> dict:
    existing_id = find_existing_text_capture("kakaopay", raw_text)
    if existing_id:
        return {"status": "duplicate", "capture_id": existing_id}

    try:
        parsed = parse_kakaopay(raw_text)
    except KakaopayParseError as e:
        capture_id = create_text_capture("kakaopay", raw_text, status="failed")
        mark_capture_status(capture_id, "failed", str(e))
        return {"status": "parse_failed", "capture_id": capture_id, "error": str(e)}

    capture_id = create_text_capture("kakaopay", raw_text, status="parsed")
    ocr_result_id = create_ocr_result(
        capture_id=capture_id,
        engine="regex_kakaopay",
        merchant_name=parsed.room,
        amount=parsed.amount,
        txn_date=parsed.txn_date,
        txn_time=parsed.txn_time,
        flow_direction=parsed.flow_direction,
        confidence=1.0,
        raw_output=json.dumps(asdict(parsed), ensure_ascii=False),
    )

    receipt_id = create_receipt(
        capture_id=capture_id,
        ocr_result_id=ocr_result_id,
        entry_type="expense",
        source_type="kakaopay",
        flow_direction=parsed.flow_direction,
        merchant_name=parsed.room,
        amount=parsed.amount,
        transaction_date=parsed.txn_date,
        transaction_time=parsed.txn_time,
        payment_method="카카오페이",
        review_status="needs_review",
    )
    classify_receipt(
        receipt_id,
        get_kakaopay_default_category_id(),
        "rule",
        note="카카오페이 송금은 라이프스타일비>소셜/네트워킹으로 기본 배정 (PROJECT_BRIEF 4절)",
    )

    return {
        "status": "ok",
        "receipt_id": receipt_id,
        "room": parsed.room,
        "amount": parsed.amount,
        "flow_direction": parsed.flow_direction,
    }


def ingest_receipt_image_manual(
    *,
    image_path: str,
    merchant_name: str,
    amount: int,
    txn_date: str,
    txn_time: str | None,
    category_id: int,
    memo: str | None = None,
) -> dict:
    """영수증 이미지를 업로드하되, OCR은 아직 연결되지 않아(3단계) 사용자가 필드를 직접 입력한다."""
    capture_id = create_image_capture(image_path, status="parsed")
    ocr_result_id = create_ocr_result(
        capture_id=capture_id,
        engine="manual",
        merchant_name=merchant_name,
        amount=amount,
        txn_date=txn_date,
        txn_time=txn_time,
        flow_direction="outflow",
        status="success",
    )
    receipt_id = create_receipt(
        capture_id=capture_id,
        ocr_result_id=ocr_result_id,
        entry_type="expense",
        source_type="receipt_image",
        flow_direction="outflow",
        merchant_name=merchant_name,
        amount=amount,
        transaction_date=txn_date,
        transaction_time=txn_time,
        memo=memo,
        review_status="confirmed",
    )
    classify_receipt(
        receipt_id, category_id, "user", note="영수증 업로드 시 사용자가 직접 분류 (OCR은 3단계에서 연결 예정)"
    )
    return {"status": "ok", "receipt_id": receipt_id}


def create_manual_entry(
    *,
    entry_type: str,
    merchant_name: str | None,
    amount: int,
    transaction_date: str,
    category_id: int,
    memo: str | None = None,
    source_type: str = "bank_manual",
) -> dict:
    """은행이체 등 자동 파싱 대상이 아닌 거래를 capture 없이 바로 기록한다."""
    flow_direction = "inflow" if entry_type == "income" else "outflow"
    receipt_id = create_receipt(
        capture_id=None,
        ocr_result_id=None,
        entry_type=entry_type,
        source_type=source_type,
        flow_direction=flow_direction,
        merchant_name=merchant_name,
        amount=amount,
        transaction_date=transaction_date,
        memo=memo,
        review_status="confirmed",
        is_manual_entry=1,
    )
    classify_receipt(receipt_id, category_id, "user", note="수동입력")
    return {"status": "ok", "receipt_id": receipt_id}


# ============================================================
# 조회
# ============================================================


def list_receipts(*, limit: int = 300, review_status: str | None = None, entry_type: str | None = None) -> list[dict]:
    query = """
        SELECT r.id, r.entry_type, r.source_type, r.flow_direction, r.merchant_name, r.amount,
               r.transaction_date, r.transaction_time, r.memo, r.review_status, r.is_manual_entry,
               cat.id AS category_id, cat.major_category, cat.minor_category, cl.classified_by
        FROM receipts r
        LEFT JOIN classifications cl ON cl.receipt_id = r.id AND cl.is_current = 1
        LEFT JOIN categories cat ON cat.id = cl.category_id
        WHERE 1 = 1
    """
    params: list = []
    if review_status:
        query += " AND r.review_status = ?"
        params.append(review_status)
    if entry_type:
        query += " AND r.entry_type = ?"
        params.append(entry_type)
    query += " ORDER BY r.transaction_date DESC, r.id DESC LIMIT ?"
    params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def summary_counts() -> dict:
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) AS n FROM receipts").fetchone()["n"]
        needs_review = conn.execute(
            "SELECT COUNT(*) AS n FROM receipts WHERE review_status = 'needs_review'"
        ).fetchone()["n"]
        this_month_expense = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total FROM receipts
            WHERE entry_type = 'expense' AND flow_direction = 'outflow'
              AND strftime('%Y-%m', transaction_date) = strftime('%Y-%m', 'now', 'localtime')
            """
        ).fetchone()["total"]
    finally:
        conn.close()
    return {
        "total_receipts": total,
        "needs_review": needs_review,
        "this_month_expense": this_month_expense,
    }
