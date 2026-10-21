"""design_story (💡) → write_story (🔒 생성기) → polish_story (문장 다듬기) → parent_review (interrupt) → reading_guide (🔒 Role B)
프롬프트 전략(state["strategy"])이 켜져 있으면 prompts/strategies/ 블록을 {{extra}} 자리에 끼운다. 다 꺼져 있으면 지금 프롬프트 그대로."""
from __future__ import annotations

from langgraph.graph import END
from langgraph.types import interrupt

from ..config import config
from ..llm import prompt, structured
from ..schemas import PolishedStory, ReadingGuide, Strategy, StoryText, design_schema
from ..state import PipelineState

_persona = prompt("_persona")


def _age(ctx):
    return ctx.child.age_months // 12, ctx.child.age_months


def _strategy(state) -> Strategy:
    return state.get("strategy") or Strategy()


def _arc_name(ctx) -> str:
    """상황별 흐름 파일 이름. 아직 안 일어난 일이면 카테고리와 상관없이 '미리 겪어 보기'."""
    return "upcoming" if ctx.situation.timing == "upcoming" else ctx.situation.category


def _design_extra(state, s: Strategy) -> str:
    blocks = []
    if s.arc:
        blocks.append(prompt("strategies/arc", arc=prompt(f"arcs/{_arc_name(state['context'])}")))
    if s.engine:
        blocks.append(prompt("strategies/engine_design"))
    if s.motif:
        blocks.append(prompt("strategies/motif_design"))
    if s.fewshot:
        blocks.append(prompt("strategies/fewshot_design"))
    return "\n\n".join(blocks)


def design_story(state: PipelineState) -> dict:
    ctx = state["context"]
    s = _strategy(state)
    fb = state.get("review_feedback")  # 재생성 scope=character/story 때 부모 요청
    feedback_block = "## 부모 요청 (이번 설계에 반드시 반영)\n" + fb if fb else ""
    d, cost = structured(
        node="design_story",
        model=config.model_main,
        schema=design_schema(s),
        system=prompt(
            "design_story",
            persona=_persona,
            context=ctx,
            summary=state.get("interview_summary") or "",
            interests=", ".join(ctx.child.interests + ([ctx.child.custom_interest] if ctx.child.custom_interest else [])) or "(없음)",
            traits=", ".join(ctx.child.traits + ([ctx.child.custom_trait] if ctx.child.custom_trait else [])) or "(없음)",
            page_count=config.page_count,
            extra=_design_extra(state, s),
            feedback=feedback_block,
        ),
        user="이야기를 설계하세요.",
        reasoning="medium",
    )
    return {"story_design": d, "cost": [cost]}


def _write_extra(s: Strategy) -> str:
    blocks = []
    if s.engine:
        blocks.append(prompt("strategies/engine_write"))
    if s.motif:
        blocks.append(prompt("strategies/motif_write"))
    return "\n".join(blocks)


def write_story(state: PipelineState) -> dict:
    ctx = state["context"]
    years, months = _age(ctx)
    fb = state.get("writer_feedback")
    feedback_block = ""
    if fb:
        prev = state.get("story")
        feedback_block = (
            "## 부모 피드백 (이 부분만 고치고 나머지는 최대한 유지)\n" + fb
            + ("\n\n## 기존 원고\n" + prev.model_dump_json(indent=2, exclude={"character_sheet", "style_guide"}) if prev else "")
        )
    s, cost = structured(
        node="write_story",
        model=config.model_main,
        schema=StoryText,
        system=prompt(
            "write_story",
            persona=_persona,
            context=ctx,
            summary=state.get("interview_summary") or "",
            design=state.get("story_design"),
            page_count=config.page_count,
            age_years=years,
            age_months=months,
            feedback=feedback_block,
            extra=_write_extra(_strategy(state)),
        ),
        user="동화를 작성하세요.",
        reasoning="medium",
    )
    s.pages.sort(key=lambda p: p.order)
    return {"story_draft": s, "story": s, "writer_feedback": None, "cost": [cost], "status": "generating_text"}


def polish_story(state: PipelineState) -> dict:
    """작가와 역할을 나눈다: 작가는 이야기·구성, 여기서는 문장만.
    쉬운 말·번역투·한 문장에 두 가지를 고친다. 쪽 수와 order가 어긋나면 원문을 그대로 쓴다."""
    ctx = state["context"]
    years, _ = _age(ctx)
    draft = state["story"]
    p, cost = structured(
        node="polish_story",
        model=config.model_main,
        schema=PolishedStory,
        system=prompt(
            "polish_story",
            persona=_persona,
            page_count=len(draft.pages),
            age_years=years,
            pages=[{"order": pg.order, "text": pg.text} for pg in draft.pages],
        ),
        user="원고의 문장을 다듬으세요.",
        reasoning="low",
    )
    polished = {pg.order: pg.text.strip() for pg in p.pages}
    if set(polished) != {pg.order for pg in draft.pages} or any(not t for t in polished.values()):
        return {"cost": [cost], "status": "generating_images"}  # 쪽이 안 맞으면 원문 유지
    story = draft.model_copy(deep=True)
    for pg in story.pages:
        pg.text = polished[pg.order]
    return {"story": story, "cost": [cost], "status": "generating_images"}


def parent_review(state: PipelineState) -> dict:
    """⏸ 부모 검토 — 텍스트+이미지+가이드 완성 후 (기획안 STEP 5~6).
    뷰어/CLI가 {action, scope, feedback}를 넣어주면 재개. 자동 재생성 없음."""
    if state.get("auto_approve"):
        return {"review_action": "approve", "regenerate_scope": None, "review_feedback": None, "status": "completed"}
    r = interrupt({
        "type": "review",
        "story": state["story"].model_dump(),
        "guide": state["guide"].model_dump() if state.get("guide") else None,
        "run_dir": state["run_dir"],
    }) or {}
    action = r.get("action", "approve")
    out = {
        "review_action": action,
        "regenerate_scope": r.get("scope"),
        "review_feedback": r.get("feedback"),
        "writer_feedback": r.get("feedback") if r.get("scope") == "text" else None,
        "status": "completed" if action == "approve" else "generating_text",
    }
    return out


def route_after_review(state: PipelineState) -> str:
    if state.get("review_action") != "regenerate":
        return END
    scope = state.get("regenerate_scope")
    if scope in ("character", "story"):
        return "design_story"
    if scope == "images":
        return "illustrate_only"
    return "write_story"  # text / None


def reading_guide(state: PipelineState) -> dict:
    ctx = state["context"]
    story = state["story"]
    g, cost = structured(
        node="reading_guide",
        model=config.model_main,
        schema=ReadingGuide,
        system=prompt(
            "reading_guide",
            persona=_persona,
            context=ctx,
            summary=state.get("interview_summary") or "",
            pages=[{"order": p.order, "text": p.text} for p in story.pages],
            min_prompts=config.guide_prompts_min,
            max_prompts=config.guide_prompts_max,
            age_months=ctx.child.age_months,
        ),
        user="독서 가이드를 작성하세요.",
        reasoning="low",
    )
    g.prompts = g.prompts[: config.guide_prompts_max]
    return {"guide": g, "cost": [cost]}
