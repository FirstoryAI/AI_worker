"""
API 없이 그래프가 끝까지 도는지 확인. (uv run python evals/mock_run.py)
LLM/이미지 호출을 가짜로 바꿔치기한다. 품질 평가가 아니라 배선 확인용.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from langgraph.types import Command

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firstory import llm, mock  # noqa: E402
from firstory.config import config  # noqa: E402
from firstory.graph import compile_graph, new_thread_id  # noqa: E402
from firstory.schemas import Strategy  # noqa: E402

_prompts: list[tuple[str, str]] = []   # (node, system) — 전략 블록이 실제로 들어갔는지 확인용


def recording_structured(**kw):
    _prompts.append((kw["node"], kw["system"]))
    return mock.fake_structured(**kw)


mock.enable()
llm.set_structured_override(recording_structured)
ALL_PAGES = list(range(1, config.page_count + 1))

data = json.loads((Path(__file__).resolve().parents[1] / "datasets/inputs/donggeul.json").read_text(encoding="utf-8"))
data.pop("scripted_answers", None)

graph = compile_graph(Path(__file__).resolve().parents[1] / "out" / "mock-checkpoints.db")

# ── 1) interrupt 경로: 인터뷰 질문 2개 + 생성 전 확인 + 검토 → 재생성(images) → 완료 ──
tid = new_thread_id()
cfg = {"configurable": {"thread_id": tid}}
r = graph.invoke({"context": data, "auto_answers": [], "auto_approve": False, "skip_images": False}, cfg)
seen = []
while "__interrupt__" in r:
    p = r["__interrupt__"][0].value
    seen.append(p["type"])
    if p["type"] == "interview":
        r = graph.invoke(Command(resume="답변 " + str(p["turn"])), cfg)
    elif p["type"] == "confirm":
        assert p["summary"] and p["end_reason"] == "sufficient" and p["context"]["parent"], p
        assert graph.get_state(cfg).next == ("confirm_generate",)
        r = graph.invoke(Command(resume={"action": "generate", "tone": "warm"}), cfg)
    elif p["type"] == "review":
        if seen.count("review") == 1:
            r = graph.invoke(Command(resume={"action": "regenerate", "scope": "images", "feedback": "3"}), cfg)
        else:
            r = graph.invoke(Command(resume={"action": "approve"}), cfg)
print("interrupts:", seen)
assert seen == ["interview", "interview", "confirm", "review", "review"], seen  # images 재생성 → render → review 다시
assert r["status"] == "completed" and len(r["guide"].prompts) == 2
assert r["tone"] == "warm"   # 확인 재개 값의 tone이 state에 남음
nodes = [c.node for c in r["cost"]]
assert nodes.count("illustrate:page3") == 2 and nodes.count("illustrate:page1") == 1, nodes  # 3페이지만 다시 그림
assert nodes.count("illustrate:sheet:포포") == 1 and nodes.count("illustrate:sheet:엄마곰") == 1, nodes  # 시트는 재사용
print("run_dir:", r["run_dir"])

# ── 1-2) 재생성 피드백: character는 설계 프롬프트에, images는 "3페이지"·"3, 5쪽"·"p3"에서 쪽 번호만 ──
cfg1b = {"configurable": {"thread_id": new_thread_id()}}
r = graph.invoke({"context": data, "auto_answers": ["a1", "a2"], "auto_confirm": True, "auto_approve": False,
                  "skip_images": False}, cfg1b)
assert "## 부모 요청" not in [s for n, s in _prompts if n == "design_story"][-1]   # 처음 설계엔 요청 블록 없음
resumes = [
    {"action": "regenerate", "scope": "character", "feedback": "토끼 말고 공룡으로 바꿔 주세요"},
    {"action": "regenerate", "scope": "images", "feedback": "3페이지"},
    {"action": "regenerate", "scope": "images", "feedback": "3, 5쪽"},
    {"action": "regenerate", "scope": "images", "feedback": "p3"},
    {"action": "regenerate", "scope": "images", "feedback": "전부 다시"},
    {"action": "regenerate", "scope": "images", "feedback": "3쪽 강아지 다리 4개로"},   # 설명 속 숫자는 쪽 아님
    {"action": "approve"},
]
redrawn = []   # 재생성 한 번마다 다시 그린 페이지
for i, cmd in enumerate(resumes):
    assert r["__interrupt__"][0].value["type"] == "review", r.get("__interrupt__")
    before = len(graph.get_state(cfg1b).values["cost"])
    r = graph.invoke(Command(resume=cmd), cfg1b)
    if i == 0:
        design = [s for n, s in _prompts if n == "design_story"][-1]
        assert "## 부모 요청" in design and "토끼 말고 공룡으로 바꿔 주세요" in design, design[-300:]
    if cmd["action"] == "regenerate" and cmd["scope"] == "images":
        new = graph.get_state(cfg1b).values["cost"][before:]
        redrawn.append(sorted(int(c.node.removeprefix("illustrate:page")) for c in new if c.node.startswith("illustrate:page")))
assert r["status"] == "completed"
assert redrawn == [[3], [3, 5], [3], ALL_PAGES, [3]], redrawn   # 숫자 없으면 기존대로 전부
print("regen feedback ok:", redrawn)

# ── 2) --auto 경로: scripted answers + auto_approve + 병렬 fan-in ──
tid2 = new_thread_id()
cfg2 = {"configurable": {"thread_id": tid2}}
r2 = graph.invoke({"context": data, "auto_answers": ["a1", "a2"], "auto_confirm": True, "auto_approve": True,
                   "skip_images": False}, cfg2)
assert "__interrupt__" not in r2
assert r2["status"] == "completed" and r2["guide"] is not None and r2["illustrations"] is not None
assert len(r2["interview_turns"]) == 2 and r2["interview_done_by"] == "sufficient"
assert all(p.status == "completed" for p in r2["illustrations"].pages)
out = Path(r2["run_dir"])
assert (out / "book.html").exists() and (out / "images" / f"page-{config.page_count:02d}.png").exists()
assert len(r2["illustrations"].character_sheets) == 2
print("auto ok:", out, "cost entries:", len(r2["cost"]))

# ── 3) 재개: 인터뷰 중간에 멈춘 thread를 get_state 로 보고 이어가기 ──
tid3 = new_thread_id()
cfg3 = {"configurable": {"thread_id": tid3}}
r3 = graph.invoke({"context": data, "auto_answers": [], "auto_approve": True, "skip_images": True}, cfg3)
assert "__interrupt__" in r3
snap = graph.get_state(cfg3)
assert snap.next == ("interview_answer",), snap.next
r3 = graph.invoke(Command(resume="skip"), cfg3)      # user_skip 경로 → 생성 전 확인에서 멈춤
assert r3["__interrupt__"][0].value["type"] == "confirm" and r3["__interrupt__"][0].value["end_reason"] == "user_skip"
assert graph.get_state(cfg3).values["status"] == "requested"   # 확인 전에는 아직 생성 시작 아님
r3 = graph.invoke(Command(resume={}), cfg3)          # LangGraph는 빈 값을 재개로 안 침 → 그대로 멈춰 있음
assert r3["__interrupt__"][0].value["type"] == "confirm"
r3 = graph.invoke(Command(resume={"action": "generate"}), cfg3)   # tone 없이 재개
assert r3["interview_done_by"] == "user_skip" and r3["status"] == "completed"
assert r3.get("tone") is None
assert r3["context"].parent.message_direction == "undecided"
assert not any("## 전략" in s for n, s in _prompts if n == "design_story")   # 전략을 안 켜면 지금 프롬프트 그대로
print("resume/skip ok")

# ── 4) 프롬프트 전략 전부 켜기: 설계에 전략 블록이 붙고 칸이 늘어난다 ──
r4 = graph.invoke({"context": data, "auto_answers": ["a1", "a2"], "auto_confirm": True, "auto_approve": True,
                   "skip_images": True,
                   "strategy": Strategy(arc=True, engine=True, fewshot=True, motif=True)},
                  {"configurable": {"thread_id": new_thread_id()}})
assert r4["story_design"].want and r4["story_design"].refrain.line == "쓱쓱!"
nodes4 = [c.node for c in r4["cost"]]
assert nodes4.count("design_story") == 1, nodes4
design = [s for n, s in _prompts if n == "design_story"][-1]
assert all(f"## 전략: {t}" in design for t in ("상황별 감정 흐름", "이야기 엔진", "반복 문구", "좋은 설계 예시"))
assert "### 다시 같이 놀기" in design   # donggeul = friend_conflict
assert "### 전략: 이야기 엔진" in [s for n, s in _prompts if n == "write_story"][-1]
print("strategy ok")

# ── 5) 프롬프트 실험: 기준 실행(2번)의 인터뷰로 전략마다 텍스트만 뽑고 채점 ──
import tempfile  # noqa: E402

from firstory import lab  # noqa: E402

exp = lab.run_experiment(out, list(lab.PRESETS), judge_on=True, workers=3, root=Path(tempfile.mkdtemp()))
e = lab.load(exp)
assert all(v["story"] and v["judge"] and not v["error"] for v in e["variants"].values()), {k: v["error"] for k, v in e["variants"].items()}
assert "attempts" in e["variants"]["engine"]["design"] and "attempts" not in e["variants"]["base"]["design"]
assert lab.score_row(e["variants"]["all"])["설계 반영"] == "4/5"
assert "| 기본 |" in (exp / "compare.md").read_text(encoding="utf-8")
print("lab ok:", exp)

print("\nALL OK")
