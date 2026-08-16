"""ocr_results / receipts / classifications / merchant_rules 담당 (분석 계층 + 학습 규칙).

이 모듈이 4개 입력 채널(카드문자/카카오페이/영수증/은행이체)을 각각
capture -> ocr_result -> receipt -> classification 흐름으로 연결하는 지점이다.
채널별 기본 분류 우선순위:
    카드문자: 1) merchant_rules에 학습된 규칙 (classified_by='rule')
             2) 없으면 Claude로 가맹점명 기반 분류 시도 (classified_by='ai', 4단계)
             3) AI도 실패/미설정이면 '미분류·확인필요' (classified_by='default')
    카카오페이: 항상 라이프스타일비>소셜/네트워킹 고정 배정 (classified_by='rule')
    영수증 이미지: Claude Vision이 OCR과 함께 분류 (classified_by='ai', 3단계)
    은행이체: 사용자가 직접 카테고리 선택 (classified_by='user')
API 키가 없거나 호출이 실패하면 vision_service/classification_service가 예외를 던지고,
호출부는 각 채널의 기존 폴백(미분류 또는 수동 입력)으로 안내한다.
"""

import json
import re
from dataclasses import asdict
from datetime import date

from app.db import dialect
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
    get_category_id,
    get_kakaopay_default_category_id,
    get_uncategorized_category_id,
)
from app.services.classification_service import (
    ClassificationNotConfiguredError,
    ClassificationRequestError,
    classify_merchant,
)
from app.services.vision_service import (
    VisionNotConfiguredError,
    VisionRequestError,
    analyze_receipt_image,
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
                f"""
                UPDATE merchant_rules
                SET category_id = ?, updated_at = {dialect.now_text_expr()}
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


def update_receipt(
    receipt_id: int,
    *,
    merchant_name: str | None,
    amount: int,
    transaction_date: str,
    memo: str | None,
    flow_direction: str | None = None,
) -> None:
    """거래내역 화면에서 사용자가 잘못 입력된 거래처/금액/날짜/메모를 직접 고칠 때 사용.
    원본 capture/ocr_result는 건드리지 않고 receipts만 갱신한다.

    flow_direction은 카카오페이처럼 방향 표시 없이 파싱돼 항상 outflow로 등록되는 채널에서
    실제로는 받은 돈이었을 때 바로잡는 용도. None이면 기존 값을 그대로 둔다."""
    conn = get_connection()
    try:
        if flow_direction is not None:
            conn.execute(
                """
                UPDATE receipts
                SET merchant_name = ?, amount = ?, transaction_date = ?, memo = ?, flow_direction = ?
                WHERE id = ?
                """,
                (merchant_name, amount, transaction_date, memo, flow_direction, receipt_id),
            )
        else:
            conn.execute(
                """
                UPDATE receipts
                SET merchant_name = ?, amount = ?, transaction_date = ?, memo = ?
                WHERE id = ?
                """,
                (merchant_name, amount, transaction_date, memo, receipt_id),
            )
        conn.commit()
    finally:
        conn.close()


def delete_receipt(receipt_id: int) -> None:
    """거래 1건을 완전히 삭제한다. classifications는 ON DELETE CASCADE로 함께 삭제된다.

    카드문자/카카오페이/영수증처럼 원본 capture가 있는 채널은 capture/ocr_result도 함께
    지운다 - 그대로 남겨두면 같은 원문을 다시 붙여넣었을 때 중복으로 간주돼 재등록이 막힌다.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT capture_id, ocr_result_id FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        if row is None:
            return
        conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
        if row["ocr_result_id"] is not None:
            conn.execute("DELETE FROM ocr_results WHERE id = ?", (row["ocr_result_id"],))
        if row["capture_id"] is not None:
            conn.execute("DELETE FROM captures WHERE id = ?", (row["capture_id"],))
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
        category_id = rule["category_id"]
        classified_by = "rule"
        rule_id = rule["id"]
        confidence = None
        note = f"학습된 규칙 매칭: '{rule['pattern']}'"
    else:
        category_id, classified_by, confidence, note = _classify_new_card_sms_merchant(
            parsed.merchant, parsed.amount
        )
        rule_id = None

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
    classify_receipt(
        receipt_id, category_id, classified_by, rule_id=rule_id, confidence=confidence, note=note
    )

    return {
        "status": "ok",
        "receipt_id": receipt_id,
        "merchant": parsed.merchant,
        "amount": parsed.amount,
        "txn_date": parsed.txn_date,
        "classified_by": classified_by,
    }


def _classify_new_card_sms_merchant(merchant_name: str, amount: int) -> tuple[int, str, float | None, str]:
    """merchant_rules에 규칙이 없는 가맹점을 Claude로 분류 시도하고, 실패하면 미분류로 폴백한다."""
    try:
        result = classify_merchant(merchant_name=merchant_name, amount=amount)
    except (ClassificationNotConfiguredError, ClassificationRequestError) as e:
        return get_uncategorized_category_id(), "default", None, f"가맹점 규칙 없음, AI 분류 불가 - 기본 미분류 ({e})"

    category_id = None
    if result.major_category and result.minor_category:
        category_id = get_category_id("expense", result.major_category, result.minor_category)

    if category_id is None:
        return get_uncategorized_category_id(), "default", result.confidence, "AI가 미분류로 판단"

    return category_id, "ai", result.confidence, f"Claude 자동 분류 (신뢰도 {result.confidence:.2f})"


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
    """영수증 이미지를 업로드하되 사용자가 필드를 직접 입력한다. OCR(analyze_receipt_image)이 실패했거나
    API 키가 없을 때, 또는 사용자가 AI 인식 결과 대신 처음부터 직접 입력하길 원할 때 쓰는 경로다."""
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
    classify_receipt(receipt_id, category_id, "user", note="영수증 업로드 시 사용자가 직접 분류")
    return {"status": "ok", "receipt_id": receipt_id}


def ingest_receipt_image_ocr(*, image_path: str, image_bytes: bytes, filename: str, memo: str | None = None) -> dict:
    """Claude Vision으로 영수증 이미지를 OCR + 분류까지 한 번에 처리한다 (PROJECT_BRIEF 3절).

    API 키가 없거나(VisionNotConfiguredError) Claude 호출이 실패하면(VisionRequestError) capture만
    남기고 상태를 'failed'로 표시한 뒤 호출부에 알린다 - 호출부(영수증 업로드 페이지)는 이 경우
    ingest_receipt_image_manual()의 수동 입력 폼으로 사용자를 안내해야 한다.
    """
    capture_id = create_image_capture(image_path, status="pending")

    try:
        analysis = analyze_receipt_image(image_bytes, filename)
    except (VisionNotConfiguredError, VisionRequestError) as e:
        mark_capture_status(capture_id, "failed", str(e))
        return {"status": "ocr_unavailable", "capture_id": capture_id, "error": str(e)}

    mark_capture_status(capture_id, "parsed")
    ocr_result_id = create_ocr_result(
        capture_id=capture_id,
        engine="claude_vision_ocr",
        merchant_name=analysis.merchant_name,
        amount=analysis.amount,
        txn_date=analysis.txn_date,
        txn_time=analysis.txn_time,
        flow_direction="outflow",
        confidence=analysis.confidence,
        raw_output=analysis.raw_response,
    )

    if analysis.major_category and analysis.minor_category:
        category_id = get_category_id("expense", analysis.major_category, analysis.minor_category)
    else:
        category_id = None
    if category_id is None:
        category_id = get_uncategorized_category_id()

    receipt_id = create_receipt(
        capture_id=capture_id,
        ocr_result_id=ocr_result_id,
        entry_type="expense",
        source_type="receipt_image",
        flow_direction="outflow",
        merchant_name=analysis.merchant_name,
        amount=analysis.amount or 0,
        transaction_date=analysis.txn_date or date.today().isoformat(),
        transaction_time=analysis.txn_time,
        memo=memo,
        review_status="needs_review",
    )
    classify_receipt(
        receipt_id,
        category_id,
        "ai",
        confidence=analysis.confidence,
        note=f"Claude Vision 자동 인식/분류 (신뢰도 {analysis.confidence:.2f})",
    )

    return {
        "status": "ok",
        "receipt_id": receipt_id,
        "merchant": analysis.merchant_name,
        "amount": analysis.amount,
        "txn_date": analysis.txn_date,
        "major_category": analysis.major_category or "미분류·확인필요",
        "minor_category": analysis.minor_category,
        "confidence": analysis.confidence,
    }


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


def list_receipts_for_month(month: str) -> list[dict]:
    """해당 월('YYYY-MM')의 전체 거래를 날짜 오름차순으로 반환한다 (백업 내보내기용)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT r.id, r.entry_type, r.source_type, r.flow_direction, r.merchant_name, r.amount,
                   r.transaction_date, r.transaction_time, r.memo, r.review_status, r.is_manual_entry,
                   cat.major_category, cat.minor_category, cl.classified_by
            FROM receipts r
            LEFT JOIN classifications cl ON cl.receipt_id = r.id AND cl.is_current = 1
            LEFT JOIN categories cat ON cat.id = cl.category_id
            WHERE {dialect.year_month_expr('r.transaction_date')} = ?
            ORDER BY r.transaction_date ASC, r.id ASC
            """,
            (month,),
        ).fetchall()
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
            f"""
            SELECT COALESCE(SUM(amount), 0) AS total FROM receipts
            WHERE entry_type = 'expense' AND flow_direction = 'outflow'
              AND {dialect.year_month_expr('transaction_date')} = {dialect.current_year_month_expr()}
            """
        ).fetchone()["total"]
    finally:
        conn.close()
    return {
        "total_receipts": total,
        "needs_review": needs_review,
        "this_month_expense": this_month_expense,
    }
