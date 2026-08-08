-- ledger-lite DB 스키마
--
-- 설계 원칙 (docs/PROJECT_BRIEF.md 6절 참고):
--   1. 수집(Collector)과 분석(Analyzer)을 테이블 레벨에서 분리한다.
--        수집 계층: captures, ocr_results   (원본 입력 + 파싱/OCR 결과, 손대지 않고 그대로 보존)
--        분석 계층: receipts, classifications (확정된 거래 + 카테고리 분류 결과)
--   2. 카드문자/카카오페이/영수증이미지는 captures -> ocr_results -> receipts 로 자동 흐름.
--      은행이체는 자동 파싱 대상이 아니므로 capture_id 없이 receipts에 바로 수동 입력된다.
--   3. 사용자의 카테고리 수정이 merchant_rules에 쌓여 다음 분류(AI/규칙 기반)에 재사용된다.
--   4. 연금/투자 관련 테이블은 존재하지 않는다. 연금 인출액은 categories의
--      수입 카테고리("연금인출유입")로 금액만 기록하고, 출처를 분석하지 않는다.

PRAGMA foreign_keys = ON;

-- ============================================================
-- 0. 카테고리 (지출 5대분류+소분류 / 수입 2종 / 시스템 상태값)
-- ============================================================
CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type      TEXT NOT NULL CHECK (entry_type IN ('expense', 'income')),
    major_category  TEXT NOT NULL,
    minor_category  TEXT NOT NULL DEFAULT '',       -- 소분류 없는 경우 '' (SQLite UNIQUE는 NULL끼리 서로 다르게 취급하므로 NULL 금지)
    is_system       INTEGER NOT NULL DEFAULT 0,     -- 1 = "미분류·확인필요" 같은 시스템 상태값(선택 불가한 정상 카테고리 아님)
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    UNIQUE (entry_type, major_category, minor_category)
);

-- ============================================================
-- 1. 수집(Collector) 계층
-- ============================================================

-- 원본 입력 그대로 저장 (카드문자 텍스트 / 카카오페이 텍스트 / 영수증 이미지 경로 / 은행이체 수동입력 마커)
CREATE TABLE IF NOT EXISTS captures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type     TEXT NOT NULL CHECK (source_type IN (
                        'card_sms',       -- 카드 승인문자 붙여넣기
                        'kakaopay',       -- 카카오페이 송금 붙여넣기
                        'receipt_image',  -- 실물 영수증 촬영/업로드
                        'bank_manual'     -- 은행 이체/출금 수동입력 (원본 텍스트 없이 참고용으로만 존재 가능)
                    )),
    raw_text        TEXT,                -- card_sms / kakaopay 원문 (source_type이 이 둘일 때 채움)
    image_path      TEXT,                -- receipt_image 파일 경로 (source_type이 receipt_image일 때 채움)
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                        'pending',   -- 아직 파싱/OCR 전
                        'parsed',    -- ocr_results 생성 완료
                        'failed',    -- 파싱/OCR 실패
                        'ignored'    -- 중복/스팸 등으로 무시됨
                    )),
    error_message   TEXT,
    captured_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_captures_source_status ON captures (source_type, status);

-- 파싱/OCR 결과 (원본은 손대지 않고 결과만 별도 저장 -> 재파싱/재분류 가능)
-- engine: card_sms/kakaopay는 정규식 파서, receipt_image는 Claude Vision(3단계 이후)
CREATE TABLE IF NOT EXISTS ocr_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id      INTEGER NOT NULL REFERENCES captures (id) ON DELETE CASCADE,
    engine          TEXT NOT NULL CHECK (engine IN (
                        'regex_card_sms',
                        'regex_kakaopay',
                        'claude_vision_ocr',
                        'manual'
                    )),
    raw_output      TEXT,                -- 파서/모델의 원본 출력 (JSON 문자열 그대로 보존)
    merchant_name   TEXT,                -- 가맹점명 / 카카오페이 대화방(상대방)명
    amount          INTEGER,             -- 원 단위
    txn_date        TEXT,                -- YYYY-MM-DD
    txn_time        TEXT,                -- HH:MM
    flow_direction  TEXT CHECK (flow_direction IN ('outflow', 'inflow')),  -- 카드=outflow, 카카오페이는 보냄/받음에 따라 다름
    confidence      REAL,                -- 0.0 ~ 1.0 (OCR/파싱 신뢰도)
    status          TEXT NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'failed', 'needs_review')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_ocr_results_capture ON ocr_results (capture_id);

-- ============================================================
-- 2. 분석(Analyzer) 계층
-- ============================================================

-- 확정된 거래(가계부 원장) 1건. 지출/수입 공통.
-- 카드문자/카카오페이/영수증에서 온 건은 capture_id/ocr_result_id로 원본을 추적할 수 있고,
-- 은행이체 수동입력 건은 capture_id 없이 바로 생성될 수 있다.
CREATE TABLE IF NOT EXISTS receipts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id      INTEGER REFERENCES captures (id) ON DELETE SET NULL,
    ocr_result_id   INTEGER REFERENCES ocr_results (id) ON DELETE SET NULL,
    entry_type      TEXT NOT NULL CHECK (entry_type IN ('expense', 'income')),
    source_type     TEXT NOT NULL CHECK (source_type IN (
                        'card_sms', 'kakaopay', 'receipt_image', 'bank_manual', 'manual_other'
                    )),
    flow_direction  TEXT NOT NULL CHECK (flow_direction IN ('outflow', 'inflow')),
    merchant_name   TEXT,                -- 가맹점/거래처/송금상대 (수입 항목은 NULL 가능)
    amount          INTEGER NOT NULL CHECK (amount >= 0),  -- 원 단위, 항상 양수. 방향은 flow_direction으로 구분
    transaction_date TEXT NOT NULL,      -- YYYY-MM-DD
    transaction_time TEXT,               -- HH:MM
    payment_method  TEXT,                -- 카드/카카오페이/계좌이체/현금 등 (선택)
    memo            TEXT,
    review_status   TEXT NOT NULL DEFAULT 'needs_review' CHECK (review_status IN ('needs_review', 'confirmed')),
    is_manual_entry INTEGER NOT NULL DEFAULT 0,  -- 은행이체 등 사용자가 처음부터 직접 입력한 건
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts (transaction_date);
CREATE INDEX IF NOT EXISTS idx_receipts_review_status ON receipts (review_status);
CREATE INDEX IF NOT EXISTS idx_receipts_source_type ON receipts (source_type);

CREATE TRIGGER IF NOT EXISTS trg_receipts_updated_at
AFTER UPDATE ON receipts
FOR EACH ROW
BEGIN
    UPDATE receipts SET updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime') WHERE id = OLD.id;
END;

-- ============================================================
-- 3. 학습 규칙 (사용자 재분류를 다음 자동분류에 반영)
-- ============================================================
CREATE TABLE IF NOT EXISTS merchant_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_type      TEXT NOT NULL DEFAULT 'contains' CHECK (match_type IN ('exact', 'contains', 'regex')),
    pattern         TEXT NOT NULL,       -- 가맹점명/상대방명 매칭 패턴
    source_type     TEXT CHECK (source_type IN ('card_sms', 'kakaopay', 'receipt_image')),  -- NULL = 전체 소스 공통
    category_id     INTEGER NOT NULL REFERENCES categories (id),
    priority        INTEGER NOT NULL DEFAULT 100,  -- 낮을수록 먼저 매칭
    created_by      TEXT NOT NULL DEFAULT 'user' CHECK (created_by IN ('user', 'system')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_merchant_rules_active ON merchant_rules (is_active, priority);

-- 카테고리 분류 결과. receipt 1건에 여러 행이 쌓일 수 있음(AI 최초 분류 -> 사용자 수정 이력 보존),
-- is_current=1인 행이 현재 유효한 분류.
CREATE TABLE IF NOT EXISTS classifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id      INTEGER NOT NULL REFERENCES receipts (id) ON DELETE CASCADE,
    category_id     INTEGER REFERENCES categories (id),   -- NULL = 미분류
    classified_by   TEXT NOT NULL CHECK (classified_by IN ('ai', 'rule', 'user', 'default')),
    rule_id         INTEGER REFERENCES merchant_rules (id),
    confidence      REAL,                -- AI 분류 신뢰도 (0.0~1.0), 규칙/수동 분류는 NULL 가능
    is_current      INTEGER NOT NULL DEFAULT 1,
    note            TEXT,                -- 분류 근거/사유 (예: "가맹점명 '스타벅스' 매칭")
    classified_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_classifications_receipt ON classifications (receipt_id);
CREATE INDEX IF NOT EXISTS idx_classifications_current ON classifications (receipt_id, is_current);

-- 오직 receipt당 하나의 "현재" 분류만 존재하도록 보장 (SQLite는 partial unique index로 표현)
CREATE UNIQUE INDEX IF NOT EXISTS uq_classifications_one_current
    ON classifications (receipt_id)
    WHERE is_current = 1;
