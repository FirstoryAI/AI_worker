"""
🔒 Role A — 인터뷰어. 백엔드 사전조사 ②.
- 매 턴: 추출 + 질문 동시 (호출 1회)
- missing_fields 는 코드가 계산해서 프롬프트에 넣는다
- 종료 판단은 AI 말 + 코드 이중 확인
- "모르겠다" 정리 질문 최대 2회, 최대 5턴, user_skip

세 노드로 나눈 이유: interrupt()는 재개 시 노드를 처음부터 다시 실행한다.
LLM 호출과 interrupt를 같은 노드에 두면 답변 받을 때마다 LLM이 다시 돈다.
  interview_step  (LLM 1회)  ──ask──▶  interview_answer (interrupt만)  ──▶  interview_step …
                             ──done─▶  interview_finish (summary)
"""
from __future__ import annotations

from langgraph.types import interrupt

from ..config import config
from ..llm import prompt, structured
from ..schemas import InterviewSummary, InterviewTurnResult, Turn
from ..state import PipelineState

_persona = prompt("_persona")
_UNSURE = ("모르", "글쎄", "어떻게 말해야", "뭐라고 해야", "둘 다")
_SKIP = ("skip", "/skip", "이만 만들어주세요", "그만")


def _same(a: str, b: str) -> bool:
    """공백·문장부호 무시하고 거의 같은 질문인지."""
    import re
    na, nb = (re.sub(r"[\s\W]+", "", x) for x in (a, b))
    if not na or not nb:
        return False
    shorter, longer = sorted((na, nb), key=len)
    return shorter in longer or len(set(na) & set(nb)) / max(len(set(na)), len(set(nb))) > 0.9


def interview_step(state: PipelineState) -> dict:
    ctx = state["context"].model_copy(deep=True)
    turns = state.get("interview_turns", [])
    clarify = state.get("clarify_count", 0)
    remaining = config.max_interview_turns - len(turns)

    r, cost = structured(
        node="interview",
        model=config.model_light,
        schema=InterviewTurnResult,
        system=prompt(
            "interview",
            persona=_persona,
            context=ctx,
            missing_fields=ctx.missing_fields() or "(없음)",
            remaining=remaining,
            clarify_remaining=max(0, config.max_clarify_turns - clarify),
            turns=[t.model_dump() for t in turns] or "(아직 없음)",
        ),
        user="다음 행동을 결정하세요.",
        reasoning="low",
    )

    # 추출 결과 병합
    for k, v in r.context_update.model_dump(exclude_none=True).items():
        setattr(ctx.parent, k, v)
    if r.moment_update:
        for k, v in r.moment_update.model_dump(exclude_none=True).items():
            setattr(ctx.moment, k, v)

    # 안전장치: 직전 질문을 그대로 반복하면 더 물을 게 없다는 뜻 → undecided 확정
    if turns and r.next_question and _same(r.next_question, turns[-1].question):
        r.status, r.next_question = "sufficient", None
        if not ctx.parent.message_direction:
            ctx.parent.message_direction = "undecided"
        if not ctx.parent.concern:
            ctx.parent.concern = turns[-1].answer

    # 정리 질문 한도 초과 → undecided 확정
    if clarify >= config.max_clarify_turns and not ctx.parent.message_direction:
        ctx.parent.message_direction = "undecided"
        if not ctx.parent.concern and turns:
            ctx.parent.concern = turns[-1].answer

    # 🔒 이중 확인
    ai_done = r.status == "sufficient" or not r.next_question
    code_done = ctx.is_sufficient()
    if ai_done and code_done:
        done_by = "sufficient"
    elif remaining <= 0:
        if not ctx.parent.message_direction:
            ctx.parent.message_direction = "undecided"
        if not ctx.parent.concern:
            ctx.parent.concern = "(인터뷰 한도 내 파악 안 됨)"
        done_by = "max_turns"
    else:
        done_by = None

    out: dict = {"context": ctx, "cost": [cost], "pending_question": None, "pending_reason": r.reason}
    if done_by:
        out["interview_done_by"] = done_by
    else:
        out["pending_question"] = r.next_question or (
            "아이에게 이번 일로 어떤 이야기를 해주고 싶으세요? 아직 잘 모르겠다고 하셔도 괜찮아요."
        )
    return out


def interview_answer(state: PipelineState) -> dict:
    q = state["pending_question"]
    turns = list(state.get("interview_turns", []))
    auto = list(state.get("auto_answers", []))

    if auto:
        answer = auto.pop(0)
    else:
        answer = interrupt({"type": "interview", "question": q, "turn": len(turns) + 1})
    answer = (answer or "").strip()

    out: dict = {"auto_answers": auto}
    if answer.lower() in _SKIP:
        ctx = state["context"].model_copy(deep=True)
        ctx.parent.message_direction = ctx.parent.message_direction or "undecided"
        ctx.parent.concern = ctx.parent.concern or "(부모가 인터뷰를 건너뜀)"
        turns.append(Turn(question=q, answer="[skip]", reason=state.get("pending_reason", "")))
        out.update(context=ctx, interview_turns=turns, interview_done_by="user_skip")
        return out

    turns.append(Turn(question=q, answer=answer, reason=state.get("pending_reason", "")))
    out["interview_turns"] = turns
    if any(k in answer for k in _UNSURE):
        out["clarify_count"] = state.get("clarify_count", 0) + 1
    return out


def interview_finish(state: PipelineState) -> dict:
    ctx = state["context"]
    turns = state.get("interview_turns", [])
    s, cost = structured(
        node="interview_summary",
        model=config.model_light,
        schema=InterviewSummary,
        system=prompt(
            "interview_summary",
            persona=_persona,
            context=ctx,
            turns=[t.model_dump() for t in turns] or "(질문 없이 종료)",
        ),
        user="한 문단으로 정리하세요.",
        reasoning="low",
    )
    return {"interview_summary": s.summary, "cost": [cost]}


def confirm_generate(state: PipelineState) -> dict:
    """⏸ 생성 전 확인 (화면 CRT-06). 인터뷰 요약·최종 Context를 보여주고 부모가 [만들기]를 누르면 재개.
    재개 값 {"action": "generate", "tone": ...}. tone 없으면 시작할 때 받은 값 유지. LLM 호출 없음 (interview_answer와 같은 이유).
    LangGraph는 빈 재개 값(None·{})을 재개로 치지 않으므로, 호출하는 쪽은 최소 {"action": "generate"}를 보낸다."""
    if state.get("auto_confirm"):
        return {"status": "generating_text"}
    r = interrupt({
        "type": "confirm",
        "summary": state.get("interview_summary"),
        "end_reason": state.get("interview_done_by"),
        "context": state["context"].model_dump(),
    })
    r = r if isinstance(r, dict) else {}
    out: dict = {"status": "generating_text"}
    if r.get("tone"):  # 안 주면 시작할 때 받은 tone 유지
        out["tone"] = r["tone"]
    return out


def route_after_step(state: PipelineState) -> str:
    return "interview_finish" if state.get("interview_done_by") else "interview_answer"


def route_after_answer(state: PipelineState) -> str:
    return "interview_finish" if state.get("interview_done_by") == "user_skip" else "interview_step"
