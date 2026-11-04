"""
LLM 호출은 전부 여기로. 모델 벤더 교체 시 이 파일만.
- structured(): 역할 프롬프트 + pydantic 스키마 → 파싱된 객체. 모든 텍스트 노드가 이것 하나로 돈다.
- structured_image(): structured()에 그림 한 장을 같이 보여 준다 (글 자리 찾기)
- prompt(): prompts/<name>.md 를 읽어 {{var}} 치환
- LangSmith 트레이싱은 환경변수(LANGSMITH_TRACING=true)만 켜면 openai 호출이 자동 기록된다.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Callable, Optional, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from .config import config
from .schemas import CostEntry

T = TypeVar("T", bound=BaseModel)

_PROMPTS = Path(__file__).parent / "prompts"


def prompt(name: str, **vars: Any) -> str:
    text = (_PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for k, v in vars.items():
        if isinstance(v, BaseModel):
            v = v.model_dump_json(indent=2, exclude_none=True)
        elif not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False, indent=2, default=str)
        text = text.replace("{{" + k + "}}", v)
    return text


# ── OpenAI 클라이언트 (LangSmith가 자동으로 래핑) ─────────────────
def _make_client() -> OpenAI:
    client = OpenAI(api_key=config.openai_api_key)
    try:
        from langsmith.wrappers import wrap_openai  # noqa: WPS433

        return wrap_openai(client)
    except Exception:  # langsmith 미설치/비활성이어도 동작
        return client


_client: Optional[OpenAI] = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = _make_client()
    return _client


# ── 테스트용 훅: structured()를 통째로 바꿔치기 ──────────────────
StructuredFn = Callable[..., BaseModel]
_override: Optional[StructuredFn] = None


def set_structured_override(fn: Optional[StructuredFn]) -> None:
    global _override
    _override = fn


def _parse(
    *, node: str, model: str, schema: Type[T], input: list[dict], reasoning: Optional[str]
) -> tuple[T, CostEntry]:
    t0 = time.time()
    kwargs: dict[str, Any] = {}
    if reasoning:
        kwargs["reasoning"] = {"effort": reasoning}
    res = client().responses.parse(model=model, input=input, text_format=schema, **kwargs)
    parsed = res.output_parsed
    if parsed is None:
        raise RuntimeError(f"[{node}] 모델이 스키마에 맞는 응답을 주지 않았습니다.")
    usage = getattr(res, "usage", None)
    cost = CostEntry(
        node=node,
        model=model,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        ms=int((time.time() - t0) * 1000),
    )
    return parsed, cost


def structured(
    *,
    node: str,
    model: str,
    schema: Type[T],
    system: str,
    user: str,
    reasoning: Optional[str] = None,
) -> tuple[T, CostEntry]:
    """Structured output 호출. (파싱된 객체, 비용 엔트리) 반환."""
    if _override is not None:
        obj = _override(node=node, model=model, schema=schema, system=system, user=user)
        return obj, CostEntry(node=node, model="mock")  # type: ignore[return-value]
    return _parse(
        node=node, model=model, schema=schema, reasoning=reasoning,
        input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )


def _data_url(image: bytes) -> str:
    mime = "image/jpeg" if image[:3] == b"\xff\xd8\xff" else "image/webp" if image[:4] == b"RIFF" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"


def structured_image(
    *,
    node: str,
    model: str,
    schema: Type[T],
    system: str,
    user: str,
    image: bytes,
    reasoning: Optional[str] = None,
) -> tuple[T, CostEntry]:
    """structured()에 그림 한 장을 같이 보여 준다 (Responses API input_image, detail high)."""
    if _override is not None:
        obj = _override(node=node, model=model, schema=schema, system=system, user=user, image=image)
        return obj, CostEntry(node=node, model="mock")  # type: ignore[return-value]
    return _parse(
        node=node, model=model, schema=schema, reasoning=reasoning,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "input_text", "text": user},
                {"type": "input_image", "image_url": _data_url(image), "detail": "high"},
            ]},
        ],
    )
