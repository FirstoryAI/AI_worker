"""그래프를 흐르는 상태. ARCHITECTURE.md §3."""
from __future__ import annotations

import operator
from typing import Annotated, Literal, Optional

from typing_extensions import TypedDict

from .schemas import (
    CostEntry,
    Illustrations,
    ReadingGuide,
    RegenerateScope,
    Strategy,
    StoryDesign,
    StoryInputContext,
    StoryStatus,
    StoryText,
    Turn,
)


class PipelineState(TypedDict, total=False):
    # 🔒 입력 Context — 1차 폼 + 인터뷰가 함께 채움
    context: StoryInputContext
    # 🔒 인터뷰
    interview_turns: list[Turn]
    clarify_count: int                       # "모르겠다" 정리 질문 횟수 (max 2)
    pending_question: Optional[str]          # interview_step → interview_answer 로 넘기는 질문
    pending_reason: str
    interview_done_by: Optional[Literal["sufficient", "max_turns", "user_skip"]]
    interview_summary: Optional[str]
    tone: Optional[Literal["plain", "warm", "undecided"]]   # 민감 주제일 때 부모가 고른 분위기 (시작 또는 confirm_generate 재개 값)
    # 💡 설계
    story_design: Optional[StoryDesign]      # 전략에 따라 StoryDesignEngine 등 칸이 더 붙은 스키마
    # 생성
    story_draft: Optional[StoryText]         # write_story 원문 (polish 전). 전후 비교용
    story: Optional[StoryText]               # polish_story 를 거친 최종본
    writer_feedback: Optional[str]           # 부모 피드백 → 작가에게 (뷰어 [다시 쓰기])
    # 검토 (parent_review interrupt 가 받는 값)
    review_action: Optional[Literal["approve", "regenerate"]]
    regenerate_scope: Optional[RegenerateScope]
    review_feedback: Optional[str]
    # 산출물
    guide: Optional[ReadingGuide]
    illustrations: Optional[Illustrations]
    # 메타
    run_dir: str
    status: StoryStatus
    cost: Annotated[list[CostEntry], operator.add]   # 병렬 브랜치가 각자 append → 합쳐짐
    # 옵션
    run_name: str                            # out/ 폴더 이름에 붙는 샘플 이름
    auto_answers: list[str]                  # --auto: 인터뷰 질문에 순서대로 자동 답변
    auto_confirm: bool                       # confirm_generate 를 멈추지 않고 바로 생성
    auto_approve: bool                       # parent_review 를 멈추지 않고 완료 처리
    skip_images: bool
    strategy: Strategy                       # 프롬프트 전략. 없으면 전부 꺼짐 (지금 프롬프트 그대로)
