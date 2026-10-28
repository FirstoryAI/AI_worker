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

from firstory import llm, mock, storage  # noqa: E402
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
assert r["status"] == "completed" and len(r["guide"].prompts) == 2 and r["guide"].synopsis
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

# ── 1-3) 실행별 결과물 경로 (G3·G4): Spring이 실행마다 새 output_prefix를 준다 ──
base = f"mock-stories/{new_thread_id()}/runs"
cfg1c = {"configurable": {"thread_id": new_thread_id()}}
r = graph.invoke({"context": data, "auto_answers": ["a1", "a2"], "auto_approve": False, "skip_images": False}, cfg1c)
assert r["__interrupt__"][0].value["type"] == "confirm"
r = graph.invoke(Command(resume={"action": "generate", "output_prefix": f"{base}/1/"}), cfg1c)
ill1 = graph.get_state(cfg1c).values["illustrations"]
assert all(pg.path == f"{base}/1/images/page-{pg.order:02d}.png" for pg in ill1.pages), ill1.pages
assert all(k.startswith(f"{base}/1/images/sheet-") for k in ill1.character_sheets.values())
assert storage.exists(f"{base}/1/03-story.json") and storage.exists(f"{base}/1/book.html")
assert r["run_dir"] == str(storage.local_path(f"{base}/1/"))

# 그림만 다시(3쪽) → 3쪽만 runs/2에 새로. 나머지 쪽과 시트는 runs/1의 key 그대로, 파일 복사 없음
r = graph.invoke(Command(resume={"action": "regenerate", "scope": "images", "feedback": "3",
                                 "output_prefix": f"{base}/2/"}), cfg1c)
ill2 = graph.get_state(cfg1c).values["illustrations"]
assert {pg.order: pg.path for pg in ill2.pages}[3] == f"{base}/2/images/page-03.png"
assert all(pg.path == f"{base}/1/images/page-{pg.order:02d}.png" for pg in ill2.pages if pg.order != 3)
assert ill2.character_sheets == ill1.character_sheets
assert not storage.exists(f"{base}/2/images/page-01.png") and not any(
    storage.exists(f"{base}/2/images/{Path(k).name}") for k in ill1.character_sheets.values())
assert storage.exists(f"{base}/1/images/page-03.png")   # 이전 실행 파일은 남는다
book = storage.local_path(f"{base}/2/book.html").read_text(encoding="utf-8")
assert 'src="../1/images/page-01.png"' in book and 'src="images/page-03.png"' in book

# 글 다시 → mock 작가가 1쪽만 고쳐 그 쪽 장면이 바뀐다. 1쪽 그림만 runs/3에 새로, 나머지 쪽과 시트는 v2의 key 그대로
r = graph.invoke(Command(resume={"action": "regenerate", "scope": "text", "feedback": "더 짧게",
                                 "output_prefix": f"{base}/3/"}), cfg1c)
ill3 = graph.get_state(cfg1c).values["illustrations"]
paths2, paths3 = ({pg.order: pg.path for pg in ill.pages} for ill in (ill2, ill3))
assert paths3[1] == f"{base}/3/images/page-01.png"
assert all(paths3[o] == paths2[o] for o in paths3 if o != 1), paths3
assert ill3.character_sheets == ill1.character_sheets
assert storage.exists(f"{base}/2/images/page-03.png") and storage.exists(f"{base}/1/03-story.json")
r = graph.invoke(Command(resume={"action": "approve"}), cfg1c)
assert r["status"] == "completed"

for bad in ["../x.png", "/abs/x.png", "a\\b.png", "c:/x.png", f"{base}/../../x.png"]:   # 저장소 밖 key는 거부
    try:
        storage.write_bytes(bad, b"x")
        raise AssertionError(f"거부 안 됨: {bad}")
    except ValueError:
        pass
print("run paths ok:", base)

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

# ── 6) 표지: 전부 그릴 때 그리고, 글 다시 만들기에서 제목이 그대로면 재사용, 제목만 바뀌면 표지만. 실패하면 None ──
from firstory.nodes import illustrate as il  # noqa: E402
from firstory.schemas import CharacterSheet, StoryPage, StoryText  # noqa: E402

il.set_image_override(mock.tiny_png)
st = StoryText(title="A", characters=[CharacterSheet(name="포포", role="protagonist", visual_description="rabbit")],
               style_guide="s", pages=[StoryPage(order=i, text="t", characters_in_scene=["포포"], image_prompt="p") for i in (1, 2)])
c1 = il.illustrate({"story": st, "output_prefix": "stories/c/runs/1/"})["illustrations"]
assert c1.cover == "stories/c/runs/1/images/cover.png" and c1.cover_title == "A"
same = il.illustrate({"story": st, "illustrations": c1, "redraw_pages": [], "output_prefix": "stories/c/runs/2/"})
assert same["illustrations"] is c1 and same["cost"] == []
retitled = il.illustrate({"story": st.model_copy(update={"title": "B"}), "illustrations": c1, "redraw_pages": [],
                          "output_prefix": "stories/c/runs/3/"})
assert retitled["illustrations"].cover == "stories/c/runs/3/images/cover.png" and retitled["illustrations"].cover_title == "B"
assert [p.path for p in retitled["illustrations"].pages] == [p.path for p in c1.pages]
assert [c.node for c in retitled["cost"]] == ["illustrate:cover"]


def no_cover(prompt, refs):
    if "Front cover" in prompt:
        raise RuntimeError("표지 실패 흉내")
    return mock.tiny_png(prompt, refs)


il.set_image_override(no_cover)
failed = il.illustrate({"story": st, "output_prefix": "stories/c/runs/4/"})["illustrations"]
assert failed.cover is None and failed.cover_title is None and all(p.status == "completed" for p in failed.pages)
print("cover ok")

print("\nALL OK")
