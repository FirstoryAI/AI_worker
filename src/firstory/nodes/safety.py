"""
위기 신호 판단 (G2, API 스펙 4장). 판단만 한다. 횟수를 세고 막는 건 Spring이 한다.
- judge: 부모 글(/v1/safety/check) 또는 완성 본문을 OK / SENSITIVE / REVISE / CRISIS로
- safety_output: 완성 동화 본문 판단 노드. polish_story 뒤에서 reading_guide·illustrate와 나란히 돈다.
  그림만 다시(illustrate_only)는 글이 그대로라 지나가지 않고, 지난 판단(output_safety)이 남는다
"""
from __future__ import annotations

from typing import Optional

from ..config import config
from ..llm import prompt, structured
from ..schemas import CostEntry, SafetyJudgement, SafetyResult, SafetySource
from ..state import PipelineState

_SOURCES: dict[str, str] = {
    "form": "부모가 동화 만들기 폼에 적은 글 (상황 설명, 아이 정보, 아이에게 전하고 싶은 말 등)",
    "interview_answer": "부모가 인터뷰 질문에 한 답",
    "regen_feedback": "부모가 완성된 동화를 다시 만들어 달라며 남긴 메모",
    "output": "AI가 만든 완성 동화 본문 (제목과 쪽마다의 글)",
}
_FALLBACK_REASON = {
    "SENSITIVE": "조심스럽게 다루면 좋은 주제라 어떤 분위기로 담을지 먼저 정하면 좋겠어요.",
    "REVISE": "아이에게 무섭거나 아프게 남을 수 있는 부분이 있어요. 그 부분을 바꿔 써 주세요.",
    "CRISIS": "아이의 안전이 걱정되는 이야기가 있어요. 동화보다 먼저 전문가와 이야기 나눠 보시면 좋겠어요.",
}


def judge(source: SafetySource, texts: list[str], question: Optional[str] = None) -> tuple[SafetyResult, CostEntry]:
    j, cost = structured(
        node="safety_output" if source == "output" else "safety_check",
        model=config.model_light,
        schema=SafetyJudgement,
        system=prompt("safety_check", source=_SOURCES[source], question=question or "(없음)"),
        user="\n\n---\n\n".join(texts),
        reasoning="low",
    )
    return _tidy(source, j), cost


def _tidy(source: SafetySource, j: SafetyJudgement) -> SafetyResult:
    """스펙 4장 형식으로: OK면 category·reason 없음, category는 REVISE·CRISIS에만, 완성 본문에는 SENSITIVE 없음."""
    level = "OK" if source == "output" and j.level == "SENSITIVE" else j.level
    if level == "OK":
        return SafetyResult(level="OK")
    category = (j.category or "other") if level in ("REVISE", "CRISIS") else None
    reason = (j.reason or "").strip() or _FALLBACK_REASON[level]
    return SafetyResult(level=level, category=category, reason=reason)


def safety_output(state: PipelineState) -> dict:
    story = state["story"]
    texts = [f"제목: {story.title}"] + [f"{p.order}쪽: {p.text}" for p in story.pages]
    result, cost = judge("output", ["\n".join(texts)])
    return {"output_safety": result, "cost": [cost]}
