"""design_story (💡) → write_story (🔒 생성기) → polish_story (문장 다듬기) → parent_review (interrupt) → reading_guide (🔒 Role B)
프롬프트 전략(state["strategy"])이 켜져 있으면 prompts/strategies/ 블록을 {{extra}} 자리에 끼운다. 다 꺼져 있으면 지금 프롬프트 그대로."""
from __future__ import annotations

from typing import Optional

from langgraph.graph import END
from langgraph.types import interrupt

from .. import storage
from ..config import config
from ..llm import prompt, structured
from ..schemas import PolishedStory, ReadingGuide, Strategy, StoryRevision, StoryText, design_schema
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
    """처음 쓰기면 원고 전체를 쓴다. 글 다시 만들기(부모 메모 + 이전 원고)면 작가는 메모 때문에 고친 쪽만 돌려주고,
    나머지 쪽·인물·화풍은 이전 원고 그대로 쓴다 (_apply_revision). 메모와 상관없는 쪽이 바뀌지 않게."""
    ctx = state["context"]
    years, months = _age(ctx)
    fb = state.get("writer_feedback")
    prev = state.get("story") if fb else None
    feedback_block = ""
    if fb:
        feedback_block = "## 부모 피드백 (글 다시 만들기)\n" + fb
        if prev:
            feedback_block += (
                "\n\n## 기존 원고\n" + prev.model_dump_json(indent=2, exclude={"characters", "style_guide"})
                + "\n\n이번에는 원고 전체가 아니라 **피드백 때문에 고쳐야 하는 쪽만** `pages`에 돌려준다. "
                "order는 기존 원고 그대로. 피드백과 상관없는 쪽은 넣지 않는다 — 기존 원고 그대로 쓰인다. "
                "고친 쪽의 `image_prompt`·`characters_in_scene`·`text_position`도 새 글에 맞춘다."
            )
    revising = prev is not None
    r, cost = structured(
        node="write_story",
        model=config.model_main,
        schema=StoryRevision if revising else StoryText,
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
        user="피드백 때문에 고쳐야 하는 쪽만 다시 쓰세요." if revising else "동화를 작성하세요.",
        reasoning="medium",
    )
    s = _apply_revision(prev, r) if revising else r
    s.pages.sort(key=lambda p: p.order)
    return {"story_draft": s, "story": s, "writer_feedback": None, "cost": [cost], "status": "generating_text",
            # 글 다시 만들기면 polish_story가 메모를 지키고, 작가가 그대로 둔 쪽은 다시 다듬지 않도록
            "revision_feedback": fb or None,
            "revision_base": {pg.order: pg.text for pg in prev.pages} if prev else None,
            # 그리고 illustrate가 장면이 바뀐 쪽만 다시 그리도록 (글만 바뀐 쪽은 그림 그대로)
            "redraw_pages": _scene_changed(prev, s) if revising else None}


def _scene_changed(prev: StoryText, new: StoryText) -> list[int]:
    scene = lambda pg: (pg.image_prompt, pg.characters_in_scene, pg.text_position)  # noqa: E731
    before = {pg.order: scene(pg) for pg in prev.pages}
    return [pg.order for pg in new.pages if before.get(pg.order) != scene(pg)]


def _apply_revision(prev: StoryText, r: StoryRevision) -> StoryText:
    """고친 쪽만 이전 원고에 끼운다. 없는 쪽·겹치는 쪽이 오거나 고친 쪽이 없으면 실패로 (부모는 다시 시도할 수 있다)."""
    orders = [pg.order for pg in r.pages]
    if not orders or len(set(orders)) != len(orders) or not set(orders) <= {pg.order for pg in prev.pages}:
        raise RuntimeError(f"[write_story] 고친 쪽이 기존 원고와 맞지 않습니다: {orders}")
    changed = {pg.order: pg for pg in r.pages}
    s = prev.model_copy(deep=True)
    s.pages = [changed.get(pg.order, pg) for pg in s.pages]
    if r.title and r.title.strip():
        s.title = r.title.strip()
    return s


def polish_story(state: PipelineState) -> dict:
    """작가와 역할을 나눈다: 작가는 이야기·구성, 여기서는 문장만.
    쉬운 말·번역투·한 문장에 두 가지를 고친다. 쪽 수와 order가 어긋나면 원문을 그대로 쓴다.
    글 다시 만들기(revision_base가 있음): 작가가 이전 글 그대로 둔 쪽은 이미 다듬은 글이라 보내지 않고,
    다시 쓴 쪽만 부모 메모와 함께 다듬는다. 메모로 고친 표현을 되돌리지 않게."""
    ctx = state["context"]
    years, _ = _age(ctx)
    draft = state["story"]
    base = state.get("revision_base") or {}
    done: dict = {"revision_feedback": None, "revision_base": None, "status": "generating_images"}
    targets = [pg for pg in draft.pages if base.get(pg.order) != pg.text]
    if not targets:
        return done
    p, cost = structured(
        node="polish_story",
        model=config.model_main,
        schema=PolishedStory,
        system=prompt(
            "polish_story",
            persona=_persona,
            page_count=len(targets),
            age_years=years,
            feedback=_polish_feedback(state.get("revision_feedback")),
            pages=[{"order": pg.order, "text": pg.text} for pg in targets],
        ),
        user="원고의 문장을 다듬으세요.",
        reasoning="low",
    )
    polished = {pg.order: pg.text.strip() for pg in p.pages}
    if set(polished) != {pg.order for pg in targets} or any(not t for t in polished.values()):
        return {**done, "cost": [cost]}  # 쪽이 안 맞으면 원문 유지
    story = draft.model_copy(deep=True)
    for pg in story.pages:
        pg.text = polished.get(pg.order, pg.text)
    return {**done, "story": story, "cost": [cost]}


def _polish_feedback(fb: Optional[str]) -> str:
    if not fb:
        return ""
    return ("### 부모 요청 (글 다시 만들기)\n"
            "작가가 아래 요청대로 원고를 다시 썼다. 받은 쪽은 이번에 다시 쓴 쪽만이다. "
            "요청으로 고친 표현은 되돌리거나 요청과 다른 쪽으로 바꾸지 않는다.\n\n" + fb.strip())


def parent_review(state: PipelineState) -> dict:
    """⏸ 부모 검토 — 텍스트+이미지+가이드 완성 후 (기획안 STEP 5~6).
    뷰어/CLI가 {action, scope, feedback}를 넣어주면 재개. 자동 재생성 없음.
    다시 만들기에 output_prefix가 있으면 그 실행의 결과물은 새 자리에 쓴다."""
    if state.get("auto_approve"):
        return {"review_action": "approve", "regenerate_scope": None, "review_feedback": None, "status": "completed"}
    r = interrupt({
        "type": "review",
        "story": state["story"].model_dump(),
        "guide": state["guide"].model_dump() if state.get("guide") else None,
        "run_dir": state["run_dir"],
    }) or {}
    return review_update(r)


def review_update(r: dict) -> dict:
    """검토 결과 {action, scope, feedback, output_prefix}를 state에 넣을 값으로.
    API 서버는 이전 버전 체크포인트에서 다시 만들 때 이 값으로 parent_review를 대신한다 (server.py review)."""
    action = r.get("action", "approve")
    out = {
        "review_action": action,
        "regenerate_scope": r.get("scope"),
        "review_feedback": r.get("feedback"),
        "writer_feedback": r.get("feedback") if r.get("scope") == "text" else None,
        "status": "completed" if action == "approve" else "generating_text",
    }
    if action == "regenerate" and r.get("output_prefix"):  # 다시 만든 실행은 새 자리에 (이전 실행 파일은 그대로)
        out.update(storage.run_fields(r["output_prefix"]))
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
            characters=[{"name": c.name, "role": c.role, "looks": c.visual_description} for c in story.characters],
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
