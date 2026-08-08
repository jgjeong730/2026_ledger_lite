"""Claude Vision을 이용한 영수증 OCR + 분류 (한 번의 API 호출로 처리).

PROJECT_BRIEF 3절: "Vision으로 영수증 이미지 직접 해석 + 카테고리 분류를 한 번의 호출로 처리".
카테고리는 자유 텍스트가 아니라 categories 테이블의 '대분류>소분류' 값만 담은 JSON Schema enum으로
강제해서, 모델이 우리 5대분류 체계 밖의 카테고리를 만들어내지 못하도록 한다.

API 키가 없으면(.env 미설정, 로컬 개발) VisionNotConfiguredError를 던진다 - 호출부(영수증 업로드
페이지)는 이 경우 2단계에서 만든 수동 입력 폼으로 안내한다 (PROJECT_BRIEF 6절: 키 없이도 로컬 모드로
전체 흐름을 테스트할 수 있어야 한다).
"""

import base64
import json
from dataclasses import dataclass
from pathlib import Path

from app import config
from app.services.category_service import list_expense_categories

_MODEL = "claude-opus-5"
_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
_UNCATEGORIZED_LABEL = "미분류"


class VisionNotConfiguredError(RuntimeError):
    """ANTHROPIC_API_KEY가 설정되지 않아 OCR을 사용할 수 없을 때."""


class VisionRequestError(RuntimeError):
    """Claude API 호출 자체는 됐지만 결과를 쓸 수 없을 때 (거부/오류)."""


@dataclass
class ReceiptAnalysis:
    merchant_name: str | None
    amount: int | None
    txn_date: str | None  # YYYY-MM-DD
    txn_time: str | None  # HH:MM 또는 None
    major_category: str | None  # None이면 미분류
    minor_category: str | None
    confidence: float
    raw_response: str  # 원본 JSON 문자열 (ocr_results.raw_output에 그대로 보존)


def is_configured() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def _category_enum() -> list[str]:
    """'대분류>소분류' 형태의 허용 카테고리 전체 목록 + 미분류."""
    options = [
        f"{major}>{minor['minor_category']}"
        for major, minors in list_expense_categories().items()
        for minor in minors
    ]
    options.append(_UNCATEGORIZED_LABEL)
    return options


def _build_request(image_b64: str, media_type: str) -> dict:
    return {
        "model": _MODEL,
        "max_tokens": 1024,
        "output_config": {
            "effort": "low",  # 영수증 인식은 깊은 추론이 필요한 작업이 아님 - 비용/지연 최소화
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "merchant_name": {"type": "string", "description": "가맹점/거래처명"},
                        "amount": {"type": "integer", "description": "영수증의 총 결제 금액(원)"},
                        "txn_date": {"type": "string", "description": "거래일, YYYY-MM-DD 형식"},
                        "txn_time": {
                            "type": ["string", "null"],
                            "description": "거래시각 HH:MM 형식, 영수증에 없으면 null",
                        },
                        "category": {
                            "type": "string",
                            "enum": _category_enum(),
                            "description": (
                                "아래 목록 중 가맹점 업종에 가장 적절한 '대분류>소분류' 하나. "
                                f"확신이 없으면 '{_UNCATEGORIZED_LABEL}'"
                            ),
                        },
                        "confidence": {
                            "type": "number",
                            "description": "category 분류에 대한 확신도, 0.0~1.0",
                        },
                    },
                    "required": ["merchant_name", "amount", "txn_date", "txn_time", "category", "confidence"],
                    "additionalProperties": False,
                },
            },
        },
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                    },
                    {
                        "type": "text",
                        "text": (
                            "이 한국 영수증 이미지를 읽고 가맹점명, 총 결제금액(원), 거래일, 거래시각을 "
                            "추출하고, 주어진 카테고리 목록 중 가장 적절한 하나를 선택해줘."
                        ),
                    },
                ],
            }
        ],
    }


def analyze_receipt_image(image_bytes: bytes, filename: str) -> ReceiptAnalysis:
    if not is_configured():
        raise VisionNotConfiguredError(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다. .env에 키를 추가하거나 수동 입력을 사용하세요."
        )

    import anthropic  # 키 없는 로컬 모드에서는 import조차 하지 않아도 앱이 뜨도록 지연 임포트

    suffix = Path(filename).suffix.lower()
    media_type = _MEDIA_TYPES.get(suffix, "image/jpeg")
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(**_build_request(image_b64, media_type))
    except anthropic.APIError as e:
        raise VisionRequestError(f"Claude API 호출 실패: {e}") from e

    if response.stop_reason == "refusal":
        raise VisionRequestError("Claude가 이 이미지 분석 요청을 거부했습니다. 수동으로 입력해주세요.")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise VisionRequestError("Claude 응답에서 결과 텍스트를 찾을 수 없습니다.")

    data = json.loads(text)

    category = data.get("category") or _UNCATEGORIZED_LABEL
    if ">" in category:
        major, minor = category.split(">", 1)
    else:
        major, minor = None, None

    amount = data.get("amount")
    return ReceiptAnalysis(
        merchant_name=data.get("merchant_name") or None,
        amount=int(amount) if amount is not None else None,
        txn_date=data.get("txn_date") or None,
        txn_time=data.get("txn_time") or None,
        major_category=major,
        minor_category=minor,
        confidence=float(data.get("confidence", 0.5)),
        raw_response=text,
    )
