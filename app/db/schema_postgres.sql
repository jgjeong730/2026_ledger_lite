-- ledger-lite DB 스키마 (Postgres/Supabase 버전)
--
-- app/db/schema.sql(SQLite)과 테이블/제약조건은 동일하게 유지한다. 차이는:
--   - INTEGER PRIMARY KEY AUTOINCREMENT -> INTEGER GENERATED ALWAYS AS IDENTITY
--   - strftime() 텍스트 기본값 -> to_char(now() AT TIME ZONE 'Asia/Seoul', ...) 텍스트 기본값
--     (날짜/시각 컬럼은 SQLite와 동일하게 TEXT로 유지 - 두 백엔드에서 같은 포맷의 문자열을 주고받기 위함)
--   - AFTER UPDATE 트리거(SQLite) -> BEFORE UPDATE 트리거 + 함수(Postgres 관용 방식)
--   - PRAGMA foreign_keys 는 Postgres에서 불필요 (FK가 항상 강제됨)

-- ============================================================
-- 0. 카테고리
-- ============================================================
CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_type      TEXT NOT NULL CHECK (entry_type IN ('expense', 'income')),
    major_category  TEXT NOT NULL,
    minor_category  TEXT NOT NULL DEFAULT '',
    is_system       INTEGER NOT NULL DEFAULT 0,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS')),
    UNIQUE (entry_type, major_category, minor_category)
);

-- ============================================================
-- 1. 수집(Collector) 계층
-- ============================================================
CREATE TABLE IF NOT EXISTS captures (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_type     TEXT NOT NULL CHECK (source_type IN (
                        'card_sms', 'kakaopay', 'receipt_image', 'bank_manual'
                    )),
    raw_text        TEXT,
    image_path      TEXT,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
                        'pending', 'parsed', 'failed', 'ignored'
                    )),
    error_message   TEXT,
    captured_at     TEXT NOT NULL DEFAULT (to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS')),
    created_at      TEXT NOT NULL DEFAULT (to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS'))
);

CREATE INDEX IF NOT EXISTS idx_captures_source_status ON captures (source_type, status);

CREATE TABLE IF NOT EXISTS ocr_results (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    capture_id      INTEGER NOT NULL REFERENCES captures (id) ON DELETE CASCADE,
    engine          TEXT NOT NULL CHECK (engine IN (
                        'regex_card_sms', 'regex_kakaopay', 'claude_vision_ocr', 'manual'
                    )),
    raw_output      TEXT,
    merchant_name   TEXT,
    amount          INTEGER,
    txn_date        TEXT,
    txn_time        TEXT,
    flow_direction  TEXT CHECK (flow_direction IN ('outflow', 'inflow')),
    confidence      REAL,
    status          TEXT NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'failed', 'needs_review')),
    created_at      TEXT NOT NULL DEFAULT (to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS'))
);

CREATE INDEX IF NOT EXISTS idx_ocr_results_capture ON ocr_results (capture_id);

-- ============================================================
-- 2. 분석(Analyzer) 계층
-- ============================================================
CREATE TABLE IF NOT EXISTS receipts (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    capture_id      INTEGER REFERENCES captures (id) ON DELETE SET NULL,
    ocr_result_id   INTEGER REFERENCES ocr_results (id) ON DELETE SET NULL,
    entry_type      TEXT NOT NULL CHECK (entry_type IN ('expense', 'income')),
    source_type     TEXT NOT NULL CHECK (source_type IN (
                        'card_sms', 'kakaopay', 'receipt_image', 'bank_manual', 'manual_other'
                    )),
    flow_direction  TEXT NOT NULL CHECK (flow_direction IN ('outflow', 'inflow')),
    merchant_name   TEXT,
    amount          INTEGER NOT NULL CHECK (amount >= 0),
    transaction_date TEXT NOT NULL,
    transaction_time TEXT,
    payment_method  TEXT,
    memo            TEXT,
    review_status   TEXT NOT NULL DEFAULT 'needs_review' CHECK (review_status IN ('needs_review', 'confirmed')),
    is_manual_entry INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS')),
    updated_at      TEXT NOT NULL DEFAULT (to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS'))
);

CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts (transaction_date);
CREATE INDEX IF NOT EXISTS idx_receipts_review_status ON receipts (review_status);
CREATE INDEX IF NOT EXISTS idx_receipts_source_type ON receipts (source_type);

CREATE OR REPLACE FUNCTION trg_receipts_set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_receipts_updated_at ON receipts;
CREATE TRIGGER trg_receipts_updated_at
BEFORE UPDATE ON receipts
FOR EACH ROW EXECUTE FUNCTION trg_receipts_set_updated_at();

-- ============================================================
-- 3. 학습 규칙
-- ============================================================
CREATE TABLE IF NOT EXISTS merchant_rules (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_type      TEXT NOT NULL DEFAULT 'contains' CHECK (match_type IN ('exact', 'contains', 'regex')),
    pattern         TEXT NOT NULL,
    source_type     TEXT CHECK (source_type IN ('card_sms', 'kakaopay', 'receipt_image')),
    category_id     INTEGER NOT NULL REFERENCES categories (id),
    priority        INTEGER NOT NULL DEFAULT 100,
    created_by      TEXT NOT NULL DEFAULT 'user' CHECK (created_by IN ('user', 'system')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS')),
    updated_at      TEXT NOT NULL DEFAULT (to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS'))
);

CREATE INDEX IF NOT EXISTS idx_merchant_rules_active ON merchant_rules (is_active, priority);

CREATE TABLE IF NOT EXISTS classifications (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    receipt_id      INTEGER NOT NULL REFERENCES receipts (id) ON DELETE CASCADE,
    category_id     INTEGER REFERENCES categories (id),
    classified_by   TEXT NOT NULL CHECK (classified_by IN ('ai', 'rule', 'user', 'default')),
    rule_id         INTEGER REFERENCES merchant_rules (id),
    confidence      REAL,
    is_current      INTEGER NOT NULL DEFAULT 1,
    note            TEXT,
    classified_at   TEXT NOT NULL DEFAULT (to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI:SS'))
);

CREATE INDEX IF NOT EXISTS idx_classifications_receipt ON classifications (receipt_id);
CREATE INDEX IF NOT EXISTS idx_classifications_current ON classifications (receipt_id, is_current);

CREATE UNIQUE INDEX IF NOT EXISTS uq_classifications_one_current
    ON classifications (receipt_id)
    WHERE is_current = 1;
