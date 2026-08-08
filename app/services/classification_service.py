"""Claude API를 이용한 텍스트 기반 가맹점 분류 (카드 승인문자용).

카카오페이는 항상 소셜/네트워킹으로 고정 배정되고, 영수증 이미지는 3단계(vision_service)에서
OCR과 함께 분류되므로, 이 모듈은 카드문자처럼 "가맹점명 텍스트만 있고 이미지는 없는" 채널에서
merchant_rules에 학습된 규칙이 없는 새 가맹점을 분류할 때만 쓴다.

카테고리는 category_service.category_enum_options()로 강제해 5대분류 체계 밖의 값을 모델이
만들어내지 못하게 한다. API 키가 없거나 호출이 실패하면 예외를 던지고, 호출부(receipt_service)는
기존처럼 '미분류·확인필요'로 폴백한다.
"""

import json
from dataclasses import dataclass

from app import config
from app.services.category_service import UNCATEGORIZED_LABEL, category_enum_options, parse_category_enum_value

_MODEL = "claude-opus-5"


class ClassificationNotConfiguredError(RuntimeError):
    """ANTHROPIC_API_KEY가 설정되지 않아 AI 분류를 사용할 수 없을 때."""


class ClassificationRequestError(RuntimeError):
    """Claude API 호출은 됐지만 결과를 쓸 수 없을 때 (거부/오류)."""


@dataclass
class MerchantClassification:
    major_category: str | None  # None이면 미분류
    minor_category: str | None
    confidence: float
    raw_response: str


def is_configured() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def classify_merchant(*, merchant_name: str, amount: int | None = None) -> MerchantClassification:
    if not is_configured():
        raise ClassificationNotConfiguredError(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다. 이 가맹점은 미분류로 등록되고 수동 재분류가 필요합니다."
        )

    import anthropic  # 키 없는 로컬 모드에서는 import조차 하지 않아도 앱이 뜨도록 지연 임포트

    prompt_lines = [f"가맹점명: {merchant_name}"]
    if amount is not None:
        prompt_lines.append(f"결제 금액: {amount:,}원")
    prompt_lines.append(
        "이 가맹점의 업종을 가맹점명만으로 추정해서, 주어진 카테고리 목록 중 가장 적절한 하나를 선택해줘."
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=512,
            output_config={
                "effort": "low",  # 가맹점명 하나로 업종을 추정하는 단순 분류 - 비용/지연 최소화
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": category_enum_options(),
                                "description": (
                                    "가맹점 업종에 가장 적절한 '대분류>소분류' 하나. "
                                    f"가맹점명만으로 업종을 특정하기 어려우면 '{UNCATEGORIZED_LABEL}'"
                                ),
                            },
                            "confidence": {"type": "number", "description": "분류 확신도, 0.0~1.0"},
                        },
                        "required": ["category", "confidence"],
                        "additionalProperties": False,
                    },
                },
            },
            messages=[{"role": "user", "content": "\n".join(prompt_lines)}],
        )
    except anthropic.APIError as e:
        raise ClassificationRequestError(f"Claude API 호출 실패: {e}") from e

    if response.stop_reason == "refusal":
        raise ClassificationRequestError("Claude가 이 분류 요청을 거부했습니다.")

    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ClassificationRequestError("Claude 응답에서 결과 텍스트를 찾을 수 없습니다.")

    data = json.loads(text)
    major, minor = parse_category_enum_value(data.get("category") or UNCATEGORIZED_LABEL)

    return MerchantClassification(
        major_category=major,
        minor_category=minor,
        confidence=float(data.get("confidence", 0.5)),
        raw_response=text,
    )
