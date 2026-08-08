# ledger-lite

은퇴 후 생활비 소비를 촬영/입력만 하면 AI가 자동 분류·분석해주는 1인용 모바일 우선 AI 가계부 MVP.

> 찍고 → AI가 읽고 → 자동 분류 → 대시보드로 확인 → 카카오톡으로 리포트 받기

연금(IRP/연저)·투자 관련 데이터/분석은 명시적으로 제외한다 (별도 프로젝트에서 관리). 연금 인출액이
입금되는 경우 "출처 분석 없이 금액만 수입으로 기록"하는 정도로만 취급한다. 자세한 배경은
[docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md) 참고.

## 개발 단계

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 프로젝트 구조 & DB 스키마 | ✅ |
| 2 | 영수증 업로드 + 수동 입력 MVP | 예정 |
| 3 | OCR 연결 (Claude Vision) | 예정 |
| 4 | AI 분류 연결 (Claude API) | 예정 |
| 5 | 대시보드 (Streamlit + Plotly) | 예정 |
| 6 | 카카오 로그인 & 알림 | 예정 |

## 기술 스택

Streamlit + 로컬 SQLite. OCR/분류는 Claude API로 통합 (3~4단계). 차트는 Plotly (5단계).

## 프로젝트 구조

```
app/
  config.py            # 환경변수, 경로 설정
  main.py              # Streamlit 진입점
  db/
    schema.sql          # DB 스키마 (DDL)
    connection.py        # SQLite 연결/초기화
    seed_categories.py   # 카테고리 기본값 시드
data/
  ledger.db             # 로컬 SQLite DB 파일 (git에 커밋하지 않음)
  receipt_images/        # 업로드된 영수증 이미지 저장 위치
tests/
  fixtures/             # 카드문자/카카오페이/영수증 샘플 데이터
  test_db_schema.py      # DB 스키마 검증 테스트
```

## DB 스키마 설계

수집(Collector)과 분석(Analyzer)을 테이블 레벨에서 분리한다.

- **수집 계층**: `captures`(원본 입력) → `ocr_results`(파싱/OCR 결과). 원본은 절대 수정하지 않고
  그대로 보존하며, 파싱/분류 로직이 바뀌어도 재처리할 수 있게 한다.
- **분석 계층**: `receipts`(확정된 거래) + `classifications`(카테고리 분류, 이력 보존).
  `classifications`는 receipt당 여러 행이 쌓일 수 있고(AI 최초 분류 → 사용자 재분류),
  `is_current=1`인 행만 유효하다.
- **카테고리**: `categories` 테이블에 지출 5대분류(고정비/변동비/라이프스타일비/가족·경조사비/
  비정기 대형지출) + 각 소분류, 수입 2종(연금인출유입/기타수입), 시스템 상태값(미분류·확인필요)을
  통합 관리한다.
- **학습 규칙**: `merchant_rules`에 사용자가 재분류한 가맹점/상대방 패턴을 쌓아 다음 자동분류에 반영한다.

### 입력 채널별 처리 방식

| 채널 | captures.source_type | 처리 |
|---|---|---|
| 카드 승인문자 | `card_sms` | 정규식 파싱 → `ocr_results` → AI/규칙 분류 |
| 카카오페이 송금 | `kakaopay` | 정규식 파싱 → `ocr_results` → **라이프스타일비 > 소셜/네트워킹 고정 배정** |
| 영수증 촬영 | `receipt_image` | Claude Vision OCR(3단계) → `ocr_results` → AI 분류 |
| 은행 계좌이체 | `bank_manual` | 자동 파싱 없음. `receipts`에 `capture_id=NULL`로 직접 수동 입력 |

연금/투자 관련 테이블은 존재하지 않는다.

## 시작하기

```bash
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env      # 필요 시 값 채우기 (1단계는 비워둬도 동작)

streamlit run app/main.py
```

첫 실행 시 `data/ledger.db`가 자동 생성되고 스키마/카테고리 시드가 채워진다.

## 테스트

```bash
pytest tests/test_db_schema.py -v
```
