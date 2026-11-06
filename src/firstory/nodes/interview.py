"""
🔒 Role A — 인터뷰어. 백엔드 사전조사 ②.
- 매 턴: 추출 + 질문 동시 (호출 1회)
- missing_fields 는 코드가 계산해서 프롬프트에 넣는다
- 종료 판단은 AI 말 + 코드 이중 확인
- "모르겠다" 정리 질문 최대 2회, 최대 config.max_interview_turns턴(15), user_skip
- 충분해지면 바로 끝내지 않고 마무리 질문(READY_QUESTION)으로 더 이야기할지 묻는다 (#48)
- 더 이야기하겠다고 하면 AI가 채운 칸을 더 구체화하는 질문을 고른다 (#53)
- 필수 칸이 차도 AI가 '동화 한 편이 그려질 만큼 구체적인가'를 보고 더 묻는다. 길어지지 않게
  첫 마무리 질문 전에는 부모 답 config.max_depth_answers번, 마무리 질문 뒤에는 config.max_more_answers번까지 (#73)

세 노드로 나눈 이유: interrupt()는 재개 시 노드를 처음부터 다시 실행한다.
LLM 호출과 interrupt를 같은 노드에 두면 답변 받을 때마다 LLM이 다시 돈다.
  interview_step  (LLM 1회)  ──ask──▶  interview_answer (interrupt만)  ──▶  interview_step …
                             ──done─▶  interview_finish (summary)
"""
from __future__ import annotations

from langgraph.types import interrupt

from .. import storage
from ..config import config
from ..llm import prompt, structured
from ..schemas import InterviewSummary, InterviewTurnResult, StoryInputContext, Turn
from ..state import PipelineState

_persona = prompt("_persona")
_UNSURE = ("모르", "글쎄", "어떻게 말해야", "뭐라고 해야", "둘 다")
_SKIP = ("skip", "/skip", "이만 만들어주세요", "그만")

# 마무리 질문. 질문 한 개로 센다 (Spring turn). "아니요"(_GO)면 끝, "네"(_MORE)면 AI가 구체화 질문, 다른 답은 새 이야기로 잇는다
READY_QUESTION = "동화를 만들 준비가 다 됐어요. 더 나누고 싶은 이야기가 있나요?"
READY_MORE = "네, 더 이야기할래요"
READY_GO = "아니요, 동화 만들러 갈게요"
MORE_QUESTION = "어떤 이야기를 더 나누고 싶으세요? 편하게 들려주세요."   # AI가 구체화할 질문을 못 고를 때
_GO = {"아니요동화만들러갈게요", "아니요", "아니", "아뇨", "없어요", "아니요없어요", "넘어갈게요", "넘어가요",
       "만들어주세요", "만들러갈게요", "동화만들러갈게요", "괜찮아요"}
_MORE = {"네더이야기할래요", "더이야기할래요", "네", "예", "응", "있어요", "네있어요"}
_DEEPEN = """## 이번 턴: 부모가 마무리 확인에서 더 이야기하고 싶다고 했다
비어 있는 항목이 없어도 `ask`로 질문 하나를 한다. 이미 채운 항목(`concern`, `message`, `response`, 아이 반응·감정) 중
더 구체적으로 알면 동화에 가장 도움이 될 것 하나를 골라 묻는다. 지금까지의 대화에 있는 질문은 다시 묻지 않는다. 답변 카드도 만든다.
"""


def _norm(x: str) -> str:
    import re
    return re.sub(r"[\s\W]+", "", x)


def _answers(turns: list[Turn]) -> list[str]:
    """마무리 질문과 건너뛰기를 뺀 부모 답 (공백·문장부호 무시)."""
    return [_norm(t.answer) for t in turns if t.question != READY_QUESTION and t.answer != "[skip]"]


def _deep_enough(turns: list[Turn]) -> bool:
    """필수 칸이 찬 뒤 구체화 질문을 그만할 때인지 (#73). 마지막 마무리 질문 뒤의 답만 센다."""
    last = max((i for i, t in enumerate(turns) if t.question == READY_QUESTION), default=None)
    if last is None:
        return len(_answers(turns)) >= config.max_depth_answers
    return len(_answers(turns[last + 1:])) >= config.max_more_answers


def _same(a: str, b: str) -> bool:
    """공백·문장부호 무시하고 거의 같은 질문인지."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    shorter, longer = sorted((na, nb), key=len)
    return shorter in longer or len(set(na) & set(nb)) / max(len(set(na)), len(set(nb))) > 0.9


def interview_step(state: PipelineState) -> dict:
    ctx = state["context"].model_copy(deep=True)
    turns = state.get("interview_turns", [])
    clarify = state.get("clarify_count", 0)
    remaining = config.max_interview_turns - len(turns)
    wants_more = bool(turns) and turns[-1].question == READY_QUESTION and _norm(turns[-1].answer) in _MORE

    r, cost = structured(
        node="interview",
        model=config.model_light,
        schema=InterviewTurnResult,
        system=prompt(
            "interview",
            persona=_persona,
            context=ctx,
            missing_fields=ctx.missing_fields() or "(없음)",
            answered=len(_answers(turns)),
            remaining=remaining,
            clarify_remaining=max(0, config.max_clarify_turns - clarify),
            turns=[t.model_dump() for t in turns] or "(아직 없음)",
            deepen=_DEEPEN if wants_more else "",
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

    # 안전장치: 이미 한 질문을 또 하면 더 물을 게 없다는 뜻 → undecided 확정.
    # 직전 것만 보지 않는다. 질문이 많아지면 몇 턴 전 질문으로 돌아가는 반복이 생긴다
    if r.next_question and any(_same(r.next_question, t.question) for t in turns):
        r.status, r.next_question = "sufficient", None
        if not ctx.parent.message_direction:
            ctx.parent.message_direction = "undecided"
        if not ctx.parent.concern:
            ctx.parent.concern = turns[-1].answer

    # 안전장치: 질문에 같은 답이 두 번 이어지면 더 할 말이 없다는 뜻 → undecided 확정 (#20).
    # 질문을 말만 바꿔 되풀이하면 _same이 못 잡는다. 마무리 질문에 새 이야기를 한 직후에는 보지 않는다
    answers = _answers(turns)
    if turns and turns[-1].question != READY_QUESTION and len(answers) >= 2 and answers[-1] and answers[-1] == answers[-2]:
        r.status, r.next_question = "sufficient", None
        if not ctx.parent.message_direction:
            ctx.parent.message_direction = "undecided"
        if not ctx.parent.concern:
            ctx.parent.concern = turns[-1].answer

    # 안전장치: 필수 칸이 다 찼으면 구체화 질문은 상한까지만 (#73)
    if r.next_question and ctx.is_sufficient() and _deep_enough(turns):
        r.status, r.next_question = "sufficient", None

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

    out: dict = {"context": ctx, "cost": [cost], "pending_question": None, "pending_choices": [],
                 "pending_reason": r.reason}
    # 더 이야기하겠다는데 AI가 구체화할 질문을 못 골랐으면(또는 반복이라 버렸으면) 열어 묻는다. 다시 마무리 질문을 하지 않는다
    if wants_more and done_by == "sufficient" and remaining > 0:
        out.update(pending_question=MORE_QUESTION, pending_reason="부모가 더 이야기하고 싶다고 함")
        return out
    if done_by == "sufficient" and remaining > 0 and not state.get("auto_confirm"):   # 자동 실행은 물을 사람이 없다
        out.update(pending_question=READY_QUESTION, pending_choices=[READY_MORE, READY_GO],
                   pending_reason="충분해져서 더 이야기할지 확인")
        return out
    if done_by:
        out["interview_done_by"] = done_by
    elif r.next_question:
        out["pending_question"] = r.next_question
        out["pending_choices"] = _choices(r.choices)
    else:  # AI가 질문 없이 ask만 준 경우. 카드는 그 질문 것이 아니라 버린다
        out["pending_question"] = "아이에게 이번 일로 어떤 이야기를 해주고 싶으세요? 아직 잘 모르겠다고 하셔도 괜찮아요."
    return out


def _choices(raw: list[str]) -> list[str]:
    """답변 카드: 빈 것·겹치는 것을 빼고 최대 config.max_interview_choices개."""
    out: list[str] = []
    for c in (x.strip() for x in raw):
        if c and c not in out:
            out.append(c)
    return out[:config.max_interview_choices]


def interview_answer(state: PipelineState) -> dict:
    q = state["pending_question"]
    turns = list(state.get("interview_turns", []))
    auto = list(state.get("auto_answers", []))

    if auto:
        answer = auto.pop(0)
    else:
        answer = interrupt({"type": "interview", "question": q, "turn": len(turns) + 1,
                            "choices": state.get("pending_choices") or []})
    answer = (answer or "").strip()

    out: dict = {"auto_answers": auto}
    # 이미 충분하다고 본 뒤라 건너뛰기도 sufficient. 앞에서 한 답을 또 쓰면 새 이야기가 아니다 (#20)
    said = _answers(turns)
    if q == READY_QUESTION and (answer.lower() in _SKIP or _norm(answer) in _GO or (said and _norm(answer) == said[-1])):
        turns.append(Turn(question=q, answer="[skip]" if answer.lower() in _SKIP else answer,
                          reason=state.get("pending_reason", "")))
        out.update(interview_turns=turns, interview_done_by="sufficient")
        return out
    if answer.lower() in _SKIP:
        ctx = state["context"].model_copy(deep=True)
        # 전하고 싶은 말을 직접 썼으면 방향을 정한 것 — undecided로 두면 요약이 '아직 정하지 못했어요'를 지어낸다
        if not ctx.parent.message:
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
    # 건너뛴 질문은 부모가 답한 게 아니다. 마무리 질문의 '만들러 갈게요'도 나눈 이야기가 아니라 뺀다
    turns = [t for t in state.get("interview_turns", [])
             if t.answer != "[skip]" and not (t.question == READY_QUESTION and _norm(t.answer) in _GO)]
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
        user="한 문단으로 정리하고, 부모에게 보여 줄 parent_summary와 situation_summary도 쓰세요.",
        reasoning="low",
    )
    return {"interview_summary": s.summary, "interview_parent_summary": s.parent_summary,
            "interview_situation_summary": s.situation_summary, "cost": [cost]}


def merge_confirmed_context(current: StoryInputContext, edited: dict) -> StoryInputContext:
    """확인 화면에서 고친 입력(Spring이 보낸 지금 입력 전체)을 인터뷰가 채운 context에 합친다.
    - child: Spring 것 (인터뷰는 아이 정보를 바꾸지 않는다)
    - situation: 바뀌었으면 Spring 것을 moment와 함께 (상황 화면이 반응·감정까지 받는다).
      안 바뀌었으면 인터뷰가 보충한 moment를 지킨다
    - parent.message: Spring 것 (전하고 싶은 말을 고쳤을 수 있다). 나머지 parent 칸은 인터뷰가 채운 그대로"""
    new = StoryInputContext.model_validate(edited)
    out = current.model_copy(deep=True)
    out.child = new.child
    if new.situation != current.situation:
        out.situation, out.moment = new.situation, new.moment
    if new.parent.message is not None:
        out.parent.message = new.parent.message
    return out


def confirm_generate(state: PipelineState) -> dict:
    """⏸ 생성 전 확인 (화면 CRT-06). 인터뷰 요약·최종 Context를 보여주고 부모가 [만들기]를 누르면 재개.
    재개 값 {"action": "generate", "tone": ..., "output_prefix": ..., "context": ..., "summary": ...}.
    tone 없으면 시작할 때 받은 값 유지, output_prefix가 있으면 이번 실행의 결과물을 그 아래에 쓴다 (없으면 form_input이 정한 자리).
    context·summary는 부모가 확인 화면에서 고친 입력과 '나누고 싶은 것' (merge_confirmed_context, 고쳐 쓴 문장은 정리에 덧붙인다).
    LLM 호출 없음 (interview_answer와 같은 이유).
    LangGraph는 빈 재개 값(None·{})을 재개로 치지 않으므로, 호출하는 쪽은 최소 {"action": "generate"}를 보낸다."""
    if state.get("auto_confirm"):
        return {"status": "generating_text"}
    r = interrupt({
        "type": "confirm",
        "summary": state.get("interview_parent_summary") or state.get("interview_summary"),   # 부모에게 보여 줄 문장
        "situation_summary": state.get("interview_situation_summary"),                       # 부모에게 보여 줄 '상황'
        "end_reason": state.get("interview_done_by"),
        "context": state["context"].model_dump(),
    })
    r = r if isinstance(r, dict) else {}
    out: dict = {"status": "generating_text"}
    if r.get("tone"):  # 안 주면 시작할 때 받은 tone 유지
        out["tone"] = r["tone"]
    if r.get("output_prefix"):
        out.update(storage.run_fields(r["output_prefix"]))
    if r.get("context"):
        out["context"] = merge_confirmed_context(state["context"], r["context"])
    edited = (r.get("summary") or "").strip()
    if edited and edited != (state.get("interview_parent_summary") or "").strip():
        out["interview_parent_summary"] = edited
        out["interview_summary"] = (f"{state.get('interview_summary') or ''}\n\n"
                                    f"부모가 확인 화면에서 고쳐 쓴 '이번 이야기에서 나누고 싶은 것': {edited}").strip()
    return out


def route_after_step(state: PipelineState) -> str:
    return "interview_finish" if state.get("interview_done_by") else "interview_answer"


def route_after_answer(state: PipelineState) -> str:
    return "interview_finish" if state.get("interview_done_by") else "interview_step"   # user_skip, 마무리 질문에서 끝
