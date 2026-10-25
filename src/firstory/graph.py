"""
FIRSTORY 그래프. ARCHITECTURE.md §2.

 form_input ─▶ interview_step ─ask─▶ interview_answer ─▶ interview_step … ─done─▶ interview_finish
                                                                                      │
                                                                                      ▼
                                                                           ⏸ confirm_generate   ← 생성 전 확인 (CRT-06)
                                                                                      │
                                                                                      ▼
                                   (regen: character/story) ─────────────────▶ design_story
                                                                                      │
                                   (regen: text) ────────────────────────────▶ write_story
                                                                                      │
                                                                                polish_story   ← 문장만 다듬기
                                                                                      │
                                                                     ┌────────────────┴────────────────┐
                                                                     ▼                                 ▼
                                                              reading_guide                       illustrate
                                                                     │                                 │
                                   (regen: images) ─▶ illustrate_only ─┐                               │
                                                                       ▼                               │
                                                                    render ◀───────────────────────────┘
                                                                       │
                                                                       ▼
                                                               ⏸ parent_review   ← 텍스트+이미지 완성 후 (기획안 STEP 5~6)
                                                                       │
                                                      approve ─────────┴───────── regenerate(scope) → 위로
                                                         │
                                                        END
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from . import schemas, storage
from .config import config
from .nodes.illustrate import illustrate, illustrate_only
from .nodes.interview import (
    confirm_generate, interview_answer, interview_finish, interview_step, route_after_answer, route_after_step,
)
from .nodes.render import render
from .nodes.story import (
    design_story, parent_review, polish_story, reading_guide, route_after_review, write_story,
)
from .schemas import StoryInputContext
from .state import PipelineState


def form_input(state: PipelineState) -> dict:
    """🔒 ① 1차 폼 검증. pydantic이 enum·필수 검사. upcoming이면 moment 비어 있어도 OK."""
    ctx = StoryInputContext.model_validate(state["context"])
    name = (state.get("run_name") or "run").replace(" ", "-")
    prefix = state.get("output_prefix") or f"{datetime.now():%Y%m%d-%H%M%S}_{name}/"
    return {"context": ctx, **storage.run_fields(prefix), "status": "requested", "cost": []}


def build_graph():
    g = StateGraph(PipelineState)
    for name, fn in [
        ("form_input", form_input),
        ("interview_step", interview_step),
        ("interview_answer", interview_answer),
        ("interview_finish", interview_finish),
        ("confirm_generate", confirm_generate),
        ("design_story", design_story),
        ("write_story", write_story),
        ("polish_story", polish_story),
        ("reading_guide", reading_guide),
        ("illustrate", illustrate),
        ("illustrate_only", illustrate_only),
        ("render", render),
        ("parent_review", parent_review),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "form_input")
    g.add_edge("form_input", "interview_step")
    g.add_conditional_edges("interview_step", route_after_step, ["interview_answer", "interview_finish"])
    g.add_conditional_edges("interview_answer", route_after_answer, ["interview_step", "interview_finish"])
    g.add_edge("interview_finish", "confirm_generate")
    g.add_edge("confirm_generate", "design_story")
    g.add_edge("design_story", "write_story")
    g.add_edge("write_story", "polish_story")
    # 🔒 ④-1: 텍스트 완료 → 가이드 ∥ 이미지 (fan-out) → render (fan-in)
    g.add_edge("polish_story", "reading_guide")
    g.add_edge("polish_story", "illustrate")
    g.add_edge(["reading_guide", "illustrate"], "render")
    g.add_edge("illustrate_only", "render")
    g.add_edge("render", "parent_review")
    g.add_conditional_edges(
        "parent_review", route_after_review,
        ["design_story", "write_story", "illustrate_only", END],
    )
    return g


# checkpointer 가 pydantic 객체를 안전하게 직렬화하도록 등록
_ALLOWED = [("firstory.schemas", n) for n in dir(schemas) if isinstance(getattr(schemas, n), type)]


def compile_graph(checkpoint_path: Path | None = None):
    path = checkpoint_path or config.checkpoint_db
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    serde = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED)
    return build_graph().compile(checkpointer=SqliteSaver(conn, serde=serde))


def new_thread_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
