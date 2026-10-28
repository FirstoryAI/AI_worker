"""
mock 모드 (API 스펙 G6). OpenAI를 부르지 않고 가짜 응답으로 그래프를 끝까지 돌린다.
  - 서버: FIRSTORY_MOCK=true 면 시작할 때 enable()
  - 테스트: evals/mock_run.py 가 같은 가짜 함수를 쓴다
품질이 아니라 배선 확인용. 상태를 들고 있지 않아서 여러 thread가 동시에 돌아도 된다.
"""
from __future__ import annotations

import re
import struct
import zlib

from . import llm
from .config import config
from .nodes import illustrate
from .schemas import (
    AfterReading, Attempt, BeforeReading, CharacterSheet, GuidePrompt, InterviewSummary, InterviewTurnResult,
    JudgeScore, ParentUpdate, PolishedPage, PolishedStory, Protagonist, ReadingGuide, Refrain, SafetyJudgement, SafetyResult,
    StoryJudgement, StoryPage, StoryRevision, StoryText, SupportingCharacter,
)


def fake_structured(*, node, model, schema, system, user):
    assert "{{" not in system, f"[{node}] 치환 안 된 자리: {system[system.index('{{'):][:40]}"
    if schema is InterviewTurnResult:
        # 지금까지 받은 답변 수로 몇 번째 턴인지 본다 (interview 프롬프트의 {{turns}})
        n = system.count('"answer":') + 1
        if n == 1:
            return InterviewTurnResult(context_update=ParentUpdate(), status="ask",
                                       next_question="당시에 어떻게 반응해주셨어요?",
                                       choices=["꼭 안아 줬어요", "괜찮다고 말해 줬어요", "뭐라고 할지 몰라 가만히 있었어요"],
                                       reason="response 비어있음")
        if n == 2:
            return InterviewTurnResult(context_update=ParentUpdate(response="안아줌", concern="뭐라고 말할지 모르겠음"),
                                       status="ask", next_question="아이 마음을 먼저 다독이고 싶으신지, 친구 입장도 생각해보게 하고 싶으신지요?",
                                       # 빈 카드·겹치는 카드·4개 넘김: 인터뷰 노드가 정리하는지 보려고 일부러 넣는다
                                       choices=["마음을 먼저 다독이고 싶어요", "친구 입장도 생각해 보게 하고 싶어요",
                                                "  ", "잘 모르겠어요", "마음을 먼저 다독이고 싶어요", "둘 다요"],
                                       reason="direction 비어있음")
        return InterviewTurnResult(context_update=ParentUpdate(message_direction="comfort_first", message="네 잘못 아니야"),
                                   status="sufficient", reason="다 채워짐")
    if schema is SafetyJudgement:   # 판단할 글은 user에 있다 (nodes/safety.py)
        s = fake_safety([user])
        return SafetyJudgement(basis="mock 표시", level=s.level, category=s.category, reason=s.reason)
    if schema is InterviewSummary:
        return InterviewSummary(summary="이 부모는 아이 마음을 먼저 받아주고 싶어하며, 친구를 나쁘게 만들고 싶지 않다.",
                                parent_summary="속상했던 마음을 먼저 알아주고 싶어요. 친구를 나쁘게 말하지는 않고 싶어요.")
    if schema.__name__.startswith("StoryDesign"):  # 전략에 따라 칸이 더 붙은 스키마도 같이
        extra = {"want": "다람쥐랑 같이 그리고 싶다",
                 "attempts": [Attempt(action=f"시도 {i}", result="안 됨" if i < 3 else "됨") for i in (1, 2, 3)],
                 "ever_since": "그 뒤로 포포는 먼저 물어봤어요.",
                 "refrain": Refrain(line="쓱쓱!", uses=["3쪽: 놀라서", "5쪽: 울면서", "9쪽: 웃으며"]),
                 "comfort_object": "분홍 크레파스"}
        return schema(protagonist=Protagonist(name="포포", species="분홍 토끼", traits=["조심스러움"]),
                      supporting=SupportingCharacter(name="엄마곰", species="갈색 곰", role="보호자", traits=["느긋함"]),
                      world="숲속 그림 교실", mirrored_situation="같이 그리던 다람쥐가 오늘은 혼자 그리겠다고 함", problem_cause="다람쥐가 혼자 그리겠다고 함",
                      values_to_honor=["아이 마음 먼저"], story_arc=["시작", "상황", "감정", "교류", "결말"],
                      **{k: v for k, v in extra.items() if k in schema.model_fields})
    if schema is StoryJudgement:
        return StoryJudgement(scores=[JudgeScore(criterion=c, feedback="근거", score=3)
                                      for c in ("재미", "개연성", "따뜻함", "눈높이", "부모 의도", "주인공 주도")],
                              arc_followed=[True, True, True, False, True])
    pages = range(1, config.page_count + 1)   # 진짜 생성과 같은 쪽수
    if schema is StoryText:
        return StoryText(title="포포와 비어 있는 자리",
                         characters=[CharacterSheet(name="포포", role="protagonist", visual_description="small pink rabbit"),
                                     CharacterSheet(name="엄마곰", role="supporting", visual_description="large brown bear")],
                         style_guide="soft watercolor",
                         pages=[StoryPage(order=i, text=f"{i}페이지. 포포는 깡충 뛰었어요.", characters_in_scene=["포포"] + (["엄마곰"] if i % 2 == 0 else []), image_prompt=f"scene {i}", text_position="top" if i % 3 == 0 else "bottom") for i in pages])
    if schema is StoryRevision:   # 글 다시 만들기: 1쪽만 고친다
        return StoryRevision(reason="mock", pages=[StoryPage(order=1, text="1페이지. 포포는 천천히 걸었어요.",
                                                             characters_in_scene=["포포"], image_prompt="scene 1 revised")])
    if schema is PolishedStory:
        given = [int(n) for n in re.findall(r'"order": (\d+)', system)]   # 글 다시 만들기면 다시 쓴 쪽만 온다
        return PolishedStory(pages=[PolishedPage(order=i, text=f"{i}쪽. 포포는 깡충 뛰었어요.") for i in given])
    if schema is ReadingGuide:
        return ReadingGuide(synopsis="토끼 포포는 친구에게 같이 놀자고 했다가 거절당해 속상했어요. 다음 날 포포는 다시 말을 걸었어요.",
                            prompts=[GuidePrompt(id="q1", after_page=3, text="포포는 어떤 기분이었을까요?", purpose="empathy", parent_hint="대답 안 해도 괜찮아요"),
                                     GuidePrompt(id="q2", after_page=8, text="내일 포포는 뭐라고 말하고 싶을까요?", purpose="predict")],
                            before_reading=BeforeReading(intent="거절당한 마음을 함께 보기", tips=["3페이지에서 잠깐 멈춰보세요"]),
                            after_reading=AfterReading(bridge_question="너도 포포처럼 느낀 적 있어?"))
    raise RuntimeError(f"mock 없음: {schema}")


def tiny_png(_prompt, _refs):
    # 1x1 PNG
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"\x00\xff\xcc\xaa"
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


# 백엔드 테스트용 표시. 글에 들어 있으면 그 level, 여러 개면 더 심각한 쪽
_SAFETY_MARKS = [
    ("[[CRISIS]]", SafetyResult(level="CRISIS", category="other", reason="아이의 안전이 걱정되는 내용이 있어요 (mock)")),
    ("[[REVISE]]", SafetyResult(level="REVISE", category="other", reason="아이에게 해로울 수 있는 방향이 담겨 있어요 (mock)")),
    ("[[SENSITIVE]]", SafetyResult(level="SENSITIVE", reason="조심스럽게 다루면 좋은 주제예요 (mock)")),
]


def fake_safety(texts: list[str]) -> SafetyResult:
    joined = "\n".join(texts)
    for mark, result in _SAFETY_MARKS:
        if mark in joined:
            return result.model_copy()
    return SafetyResult(level="OK")


def enable() -> None:
    llm.set_structured_override(fake_structured)
    illustrate.set_image_override(tiny_png)
