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
from firstory.nodes import interview as iv  # noqa: E402
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

# ── 1) interrupt 경로: 인터뷰 질문 2개 + 마무리 질문 + 생성 전 확인 + 검토 → 재생성(images) → 완료 ──
tid = new_thread_id()
cfg = {"configurable": {"thread_id": tid}}
r = graph.invoke({"context": data, "auto_answers": [], "auto_approve": False, "skip_images": False}, cfg)
seen = []
while "__interrupt__" in r:
    p = r["__interrupt__"][0].value
    seen.append(p["type"])
    if p["type"] == "interview" and p["question"] == iv.READY_QUESTION:
        assert p["turn"] == 3 and p["choices"] == [iv.READY_MORE, iv.READY_GO], p
        r = graph.invoke(Command(resume=iv.READY_GO), cfg)
    elif p["type"] == "interview":
        r = graph.invoke(Command(resume="답변 " + str(p["turn"])), cfg)
    elif p["type"] == "confirm":
        assert p["summary"] and p["situation_summary"] and p["end_reason"] == "sufficient" and p["context"]["parent"], p
        assert graph.get_state(cfg).next == ("confirm_generate",)
        r = graph.invoke(Command(resume={"action": "generate", "tone": "warm"}), cfg)
    elif p["type"] == "review":
        if seen.count("review") == 1:
            r = graph.invoke(Command(resume={"action": "regenerate", "scope": "images", "feedback": "3"}), cfg)
        else:
            r = graph.invoke(Command(resume={"action": "approve"}), cfg)
print("interrupts:", seen)
assert seen == ["interview", "interview", "interview", "confirm", "review", "review"], seen  # images 재생성 → render → review 다시
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
assert r["__interrupt__"][0].value["question"] == iv.READY_QUESTION   # auto_confirm이 아니면 마무리 질문은 사람이 답한다
r = graph.invoke(Command(resume=iv.READY_GO), cfg1c)
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

# ── 그림이 콘텐츠 정책에 막히면 장면을 순화해 한 번 더 (#37). 순화해도 막히면 그 쪽만 failed ──
policy_prompts: list[str] = []


def policy(prompt, refs):
    policy_prompts.append(prompt)
    if "Scene" in prompt and ("scene-a" in prompt and "gentle" not in prompt or "scene-b" in prompt):
        raise il.PolicyBlocked("safety system 흉내")
    return mock.tiny_png(prompt, refs)


il.set_image_override(policy)
st2 = st.model_copy(update={"pages": [StoryPage(order=1, text="t", characters_in_scene=["포포"], image_prompt="scene-a"),
                                      StoryPage(order=2, text="t", characters_in_scene=["포포"], image_prompt="scene-b")]})
blocked = il.illustrate({"story": st2, "output_prefix": "stories/c/runs/5/"})
p1, p2 = blocked["illustrations"].pages
assert p1.status == "completed" and any("gentle scene-a" in x for x in policy_prompts)   # 순화한 장면으로 다시 그림
assert p2.status == "failed" and "safety system" in p2.error                              # 순화해도 막힘 → 그 쪽만 실패
assert sum(c.node == "illustrate:soften" for c in blocked["cost"]) == 2
assert blocked["illustrations"].cover                                                      # 다른 그림은 그대로
il.set_image_override(mock.tiny_png)
print("policy retry ok")

# ── 쪽·표지는 받은 형식대로 key 확장자를 정한다 (#32). 시트는 그대로 PNG ──
def webp_pages(prompt, refs):
    return b"RIFF\x00\x00\x00\x00WEBPVP8 " if refs else mock.tiny_png(prompt, refs)   # 참조가 있으면 쪽·표지(edit)


il.set_image_override(webp_pages)
w = il.illustrate({"story": st, "output_prefix": "stories/c/runs/6/"})["illustrations"]
assert [p.path for p in w.pages] == ["stories/c/runs/6/images/page-01.webp", "stories/c/runs/6/images/page-02.webp"]
assert w.cover == "stories/c/runs/6/images/cover.webp" and all(k.endswith(".png") for k in w.character_sheets.values())
il.set_image_override(mock.tiny_png)
print("webp ok")

# ── 그림만 다시: 쪽 선택(regenerate_pages)과 부모 메모(review_feedback)를 따로 (#46) ──
memo_prompts: list[str] = []


def record(prompt, refs):
    memo_prompts.append(prompt)
    return mock.tiny_png(prompt, refs)


il.set_image_override(record)
base = {"story": st, "illustrations": c1, "output_prefix": "stories/c/runs/7/"}
memo = "2쪽 포포가 더 활짝 웃게 해 주세요"
o = il.illustrate_only(base | {"regenerate_pages": [1], "review_feedback": memo})   # 메모의 "2쪽"이 아니라 고른 쪽만
assert [c.node for c in o["cost"] if c.node.startswith("illustrate:")] == ["illustrate:page1"], o["cost"]
assert len(memo_prompts) == 1 and memo in memo_prompts[0] and "Parent's request" in memo_prompts[0]
memo_prompts.clear()
o = il.illustrate_only(base | {"regenerate_pages": [], "review_feedback": memo})       # []는 전부, 메모는 쪽마다
assert sorted(c.node for c in o["cost"] if c.node.startswith("illustrate:page")) == ["illustrate:page1", "illustrate:page2"]
assert all(memo in p for p in memo_prompts if "Scene" in p) and not any(memo in p for p in memo_prompts if "Front cover" in p)
memo_prompts.clear()
o = il.illustrate_only(base | {"regenerate_pages": [2], "review_feedback": None})      # 메모 없으면 프롬프트 그대로
assert len(memo_prompts) == 1 and "Parent's request" not in memo_prompts[0]
memo_prompts.clear()
o = il.illustrate_only(base | {"review_feedback": "2"})                                # CLI·뷰어: 쪽 번호만이면 메모 아님
assert [c.node for c in o["cost"] if c.node.startswith("illustrate:")] == ["illustrate:page2"] and "Parent's request" not in memo_prompts[0]
assert il._memo("3, 5쪽") is None and il._memo(" ") is None and il._memo(memo) == memo
from firstory.nodes.story import review_update  # noqa: E402
assert review_update({"action": "regenerate", "scope": "images", "pages": [], "feedback": memo})["regenerate_pages"] == []
assert review_update({"action": "regenerate", "scope": "text", "pages": [3], "feedback": "x"})["regenerate_pages"] is None
il.set_image_override(mock.tiny_png)
print("image regen memo ok")

# ── 인터뷰 상한(15)과 반복: 몇 턴 전 질문으로 돌아가도 끝내고, 15턴째에는 max_turns ──
from firstory.schemas import InterviewTurnResult, ParentUpdate, StoryInputContext, Turn  # noqa: E402

assert config.max_interview_turns == 15
ctx0 = StoryInputContext.model_validate(data)
asked = [Turn(question=f"질문 {i}번째는 무엇인가요?", answer=f"답 {i}") for i in range(1, 4)]   # 같은 답이면 #20 안전장치가 먼저 끝낸다


def asks(question):
    return lambda **kw: InterviewTurnResult(context_update=ParentUpdate(), status="ask", next_question=question,
                                            choices=["예"], reason="r")


llm.set_structured_override(asks("질문 1번째는 무엇인가요?"))   # 직전(3번째)이 아니라 첫 질문을 다시
o = iv.interview_step({"context": ctx0, "interview_turns": asked})
assert "interview_done_by" not in o and o["pending_question"] == iv.READY_QUESTION, o   # 끝내기 전에 마무리 질문
assert o["context"].parent.message_direction == "undecided"
o = iv.interview_step({"context": ctx0, "interview_turns": asked, "auto_confirm": True})
assert o["interview_done_by"] == "sufficient" and o["pending_question"] is None, o   # 자동 실행은 묻지 않는다

llm.set_structured_override(asks("새로운 질문인가요?"))
o = iv.interview_step({"context": ctx0, "interview_turns": asked})
assert "interview_done_by" not in o and o["pending_question"] == "새로운 질문인가요?"
many = [Turn(question=f"서로 다른 질문 {chr(0xAC00 + i * 97)}?", answer=f"답 {i}") for i in range(14)]
o = iv.interview_step({"context": ctx0, "interview_turns": many})
assert "interview_done_by" not in o and o["pending_question"] == "새로운 질문인가요?"   # 14개 답한 뒤에도 15번째 질문
o = iv.interview_step({"context": ctx0, "interview_turns": many + [Turn(question="열다섯째?", answer="답 15")]})
assert o["interview_done_by"] == "max_turns", o

# ── 마무리 질문 (#48) ──
llm.set_structured_override(lambda **kw: InterviewTurnResult(context_update=ParentUpdate(), status="sufficient", reason="r"))
done = ctx0.model_copy(deep=True)
done.parent.concern, done.parent.message_direction, done.parent.response = "고민", "comfort_first", "안아줌"
assert done.is_sufficient()
o = iv.interview_step({"context": done, "interview_turns": many})   # 15번째 질문으로 마무리 질문
assert o["pending_question"] == iv.READY_QUESTION and o["pending_choices"] == [iv.READY_MORE, iv.READY_GO], o
o = iv.interview_step({"context": done, "interview_turns": many + [Turn(question="열다섯째?", answer="답 15")]})
assert o["interview_done_by"] == "sufficient" and o["pending_question"] is None, o   # 남은 질문이 없으면 묻지 않고 끝
more = asked + [Turn(question=iv.READY_QUESTION, answer=iv.READY_MORE)]
o = iv.interview_step({"context": done, "interview_turns": more})   # '네'인데 AI가 구체화할 질문을 못 고르면 열어 묻는다
assert o["pending_question"] == iv.MORE_QUESTION and o["pending_choices"] == [] and "interview_done_by" not in o, o
seen_prompts = []


def deepens(**kw):
    seen_prompts.append(kw["system"])
    return asks("그때 아이를 안아 줬을 때 아이는 어떤 표정이었어요?")(**kw)


llm.set_structured_override(deepens)
for yes in (iv.READY_MORE, "네", "있어요!"):   # 칸이 다 채워졌어도 AI가 고른 구체화 질문과 카드
    o = iv.interview_step({"context": done, "interview_turns": asked + [Turn(question=iv.READY_QUESTION, answer=yes)]})
    assert o["pending_question"] == "그때 아이를 안아 줬을 때 아이는 어떤 표정이었어요?" and o["pending_choices"] == ["예"], o
    assert "## 이번 턴: 부모가 마무리 확인에서 더 이야기하고 싶다고 했다" in seen_prompts[-1]
iv.interview_step({"context": ctx0, "interview_turns": asked})
assert "{{deepen}}" not in seen_prompts[-1] and "## 이번 턴" not in seen_prompts[-1]   # 평소에는 안 붙는다
llm.set_structured_override(lambda **kw: InterviewTurnResult(context_update=ParentUpdate(), status="sufficient", reason="r"))
told = asked + [Turn(question=iv.READY_QUESTION, answer="사실 동생이 생겨서 더 예민해요")]
assert iv.interview_step({"context": done, "interview_turns": told})["pending_question"] == iv.READY_QUESTION   # 새 이야기 뒤 다시 확인

ready = {"context": done, "interview_turns": asked, "pending_question": iv.READY_QUESTION}
for a, kept in ((iv.READY_GO, iv.READY_GO), ("아니요!", "아니요!"), ("없어요", "없어요"), ("skip", "[skip]")):
    o = iv.interview_answer(ready | {"auto_answers": [a]})
    assert o["interview_done_by"] == "sufficient" and o["interview_turns"][-1].answer == kept, o
    assert iv.route_after_answer(o) == "interview_finish"
for a in (iv.READY_MORE, "네", "사실 동생이 생겨서 더 예민해요"):
    o = iv.interview_answer(ready | {"auto_answers": [a]})
    assert "interview_done_by" not in o and o["interview_turns"][-1].answer == a, o
    assert iv.route_after_answer(o) == "interview_step"

finish_prompts = []
llm.set_structured_override(lambda **kw: finish_prompts.append(kw["system"]) or mock.fake_structured(**kw))
iv.interview_finish({"context": done, "interview_turns": asked + [
    Turn(question=iv.READY_QUESTION, answer="사실 동생이 생겨서 더 예민해요"), Turn(question=iv.READY_QUESTION, answer=iv.READY_GO)]})
assert "동생이 생겨서" in finish_prompts[-1] and iv.READY_GO not in finish_prompts[-1]   # '만들러 갈게요'는 요약에 안 넘김
llm.set_structured_override(recording_structured)
print("interview limit / ready ok")

# ── 같은 답이 두 번 이어지면 더 묻지 않는다 (#20). 질문을 말만 바꿔 되풀이해도 끝낸다 ──
llm.set_structured_override(asks("그때 가장 마음에 걸렸던 건 어떤 쪽이었나요?"))
same = "문 앞에서 한참 서 있었어요"
two = [Turn(question="아이에게 무엇을 전하고 싶으세요?", answer=same), Turn(question="그때 가장 걱정된 건요?", answer=same + "!")]
o = iv.interview_step({"context": ctx0, "interview_turns": two})
assert o["pending_question"] == iv.READY_QUESTION and "interview_done_by" not in o, o        # 마무리 질문으로
assert o["context"].parent.message_direction == "undecided" and o["context"].parent.concern == same + "!"
o = iv.interview_step({"context": ctx0, "interview_turns": [two[0], Turn(question="그때 가장 걱정된 건요?", answer="다른 답")]})
assert o["pending_question"] == "그때 가장 마음에 걸렸던 건 어떤 쪽이었나요?", o                  # 다른 답이면 그대로 묻는다
after_ready = two + [Turn(question=iv.READY_QUESTION, answer="사실 동생이 생겼어요")]
o = iv.interview_step({"context": ctx0, "interview_turns": after_ready})                     # 마무리 질문에 새 이야기 직후는 보지 않는다
assert o["pending_question"] == "그때 가장 마음에 걸렸던 건 어떤 쪽이었나요?", o
skipped = [two[0], Turn(question="q", answer="[skip]"), Turn(question="r", answer=same)]
assert iv.interview_step({"context": ctx0, "interview_turns": skipped})["pending_question"] == iv.READY_QUESTION   # 건너뛴 것은 빼고 본다
o = iv.interview_answer({"context": ctx0, "interview_turns": two, "pending_question": iv.READY_QUESTION, "auto_answers": [same]})
assert o["interview_done_by"] == "sufficient" and o["interview_turns"][-1].answer == same, o   # 마무리 질문에 같은 답 = 새 이야기 없음
o = iv.interview_answer({"context": ctx0, "interview_turns": two, "pending_question": iv.READY_QUESTION, "auto_answers": ["skip"]})
assert o["interview_turns"][-1].answer == "[skip]"
llm.set_structured_override(recording_structured)
print("repeated answer ok")

# ── 8) 글 덩어리 배치 (text_blocks): 쪽 그림마다 덩어리·자리를 정해 PageImage에 싣는다 ──
import io  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
from collections import Counter  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402

from firstory.nodes import layout  # noqa: E402
from firstory.schemas import PolishedPage, PolishedStory, StoryRevision, TextChunking  # noqa: E402


def joined(s: str) -> str:
    return re.sub(r"\s", "", s)


def lines_of(pi) -> str:
    return joined("".join(line for b in pi.text_blocks for para in b.paragraphs for line in para))


def striped_png(clear=None) -> bytes:
    """전체가 줄무늬(복잡)인 그림. clear=(x0,y0,x1,y1)(%)는 흰 바탕으로 비워 둔다."""
    img = Image.new("RGB", (layout.W, layout.H), "white")
    d = ImageDraw.Draw(img)
    for x in range(0, layout.W, 24):
        d.rectangle([x, 0, x + 11, layout.H], fill=(40, 40, 40))
    if clear:
        x0, y0, x1, y1 = clear
        d.rectangle([x0 / 100 * layout.W, y0 / 100 * layout.H, x1 / 100 * layout.W, y1 / 100 * layout.H], fill="white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# 8-1) 처음 만들기: 그림이 있는 모든 쪽에 덩어리 1~2개, 줄을 이으면 원문
for pg in r2["story"].pages:
    pi = next(x for x in r2["illustrations"].pages if x.order == pg.order)
    assert pi.text_blocks and 1 <= len(pi.text_blocks) <= 2, pi
    assert lines_of(pi) == joined(pg.text), (lines_of(pi), pg.text)
    assert all(b.color in ("dark", "light") and 0 <= b.x <= 100 and 0 <= b.y <= 100 for b in pi.text_blocks)
n2 = [c.node for c in r2["cost"]]
assert all(f"layout:place:page{o}" in n2 for o in ALL_PAGES) and "layout:chunk" not in n2 and "layout:place" not in n2, n2
assert "layout:chunk:page1" in n2   # 줄이 둘이라 덩어리 나누기를 부른다

# 8-2) 1×1 가짜 그림(단색)에서도 mock 자리(x 5, y 7)가 settle을 통과한다
busy_flat = layout.Busy(mock.tiny_png("", []))
assert layout.settle(busy_flat, [[["가나다.", "라마바."]]], [{"x": 5, "y": 7, "color": "dark"}]) == [{"x": 5.0, "y": 7.0, "color": "dark"}]

# 8-3) 그림이 실패한 쪽은 text_blocks가 없다
st5 = StoryText(title="T", characters=[CharacterSheet(name="포포", role="protagonist", visual_description="rabbit")], style_guide="s",
                pages=[StoryPage(order=i, text=f"{i}쪽 첫 줄이에요. 둘째 줄이에요.", characters_in_scene=["포포"], image_prompt=f"scene-{i}")
                       for i in range(1, 6)])


def fail5(prompt, refs):
    if "Scene" in prompt and "scene-5" in prompt:
        raise RuntimeError("5쪽 실패 흉내")
    return mock.tiny_png(prompt, refs)


il.set_image_override(fail5)
f5 = il.illustrate({"story": st5, "output_prefix": "stories/t/runs/1/"})["illustrations"]
assert [p.status for p in f5.pages] == ["completed"] * 4 + ["failed"]
assert f5.pages[4].text_blocks is None and all(p.text_blocks for p in f5.pages[:4])
print("failed page has no blocks ok")

# 8-4) 글 다시 만들기: 작가가 1쪽 글만 고치고 장면은 그대로 → 그림 key 그대로, text_blocks는 새 글
cfg8 = {"configurable": {"thread_id": new_thread_id()}}
llm.set_structured_override(recording_structured)
il.set_image_override(mock.tiny_png)
r8 = graph.invoke({"context": data, "auto_answers": ["a1", "a2"], "auto_confirm": True, "auto_approve": False, "skip_images": False,
                   }, cfg8)
assert r8["__interrupt__"][0].value["type"] == "review"
v1 = graph.get_state(cfg8).values
first = next(pg for pg in v1["story"].pages if pg.order == 1)


def text_only_1(**kw):
    if kw["schema"] is StoryRevision:   # 장면(image_prompt·characters_in_scene·text_position)은 첫 원고와 같게
        return StoryRevision(reason="mock", pages=[first.model_copy(update={"text": "1페이지. 포포는 천천히 걸었어요. 바람이 불었어요."})])
    if kw["schema"] is PolishedStory:   # 다듬기는 다시 쓴 쪽(1쪽)만 받는다
        return PolishedStory(pages=[PolishedPage(order=1, text="1쪽. 포포는 천천히 걸었어요. 바람이 불었어요.")])
    return recording_structured(**kw)


llm.set_structured_override(text_only_1)
calls8: list[str] = []
il.set_image_override(lambda p, refs: calls8.append(p) or mock.tiny_png(p, refs))
before = len(v1["cost"])
r8 = graph.invoke(Command(resume={"action": "regenerate", "scope": "text", "feedback": "1쪽 글만"}), cfg8)
v2 = graph.get_state(cfg8).values
pages1, pages2 = ({pi.order: pi for pi in v["illustrations"].pages} for v in (v1, v2))
assert not any("Scene" in p for p in calls8), "장면이 같은데 그림을 다시 그렸다"
assert pages2[1].path == pages1[1].path                                        # 그림 key 그대로
new_text = next(pg.text for pg in v2["story"].pages if pg.order == 1)
old_text = first.text
assert "천천히" in new_text and new_text != old_text and lines_of(pages2[1]) == joined(new_text), (new_text, pages2[1].text_blocks)   # 다듬기 뒤 최종 글
assert lines_of(pages1[1]) != lines_of(pages2[1])
assert all(pages2[o].text_blocks == pages1[o].text_blocks for o in pages1 if o != 1)   # 글 그대로인 쪽은 다시 안 함
new_nodes = [c.node for c in v2["cost"][before:]]
assert "layout:place:page1" in new_nodes and not any(n.startswith("layout:") and n.endswith(tuple(f"page{o}" for o in range(2, 20)))
                                                      for n in new_nodes), new_nodes
assert not any(n.startswith("illustrate:page") for n in new_nodes)
il.set_image_override(mock.tiny_png)
llm.set_structured_override(recording_structured)
print("text regen relayouts reused image ok")

# 8-5) 자리를 못 찾으면: 덩어리 합치기 → 다시 그리기(실행당 2쪽까지) → 기본 자리
def two_blocks(**kw):   # 첫 줄 / 나머지 두 덩어리로 나누고 둘 다 같은 자리(5,7)를 달라고 한다 → 겹쳐서 settle이 찾기를 해야 한다
    if kw["schema"] is TextChunking:
        n = len(re.findall(r"^\d+: ", kw["system"], re.M))
        return TextChunking(blocks=[[[0]], [list(range(1, n))]] if n > 1 else [[[0]]])
    return mock.fake_structured(**kw)


places: list[int] = []   # place_page가 받은 덩어리 수
orig_place = layout.place_page


def spy_place(image, blocks):
    places.append(len(blocks))
    return orig_place(image, blocks)


il.place_page = spy_place
llm.set_structured_override(two_blocks)
page_calls = Counter()
lock = threading.Lock()


def all_busy(prompt, refs):
    if refs and "Scene" in prompt:
        with lock:
            page_calls[re.search(r"scene-\d", prompt).group(0)] += 1
        return striped_png()
    return mock.tiny_png(prompt, refs)


il.set_image_override(all_busy)
st8 = st5.model_copy(update={"pages": [pg.model_copy(update={"text": f"{pg.order}쪽 첫 줄이에요. 둘째 줄이에요. 셋째 줄이에요."}) for pg in st5.pages]})
b8 = il.illustrate({"story": st8, "output_prefix": "stories/t/runs/2/"})
assert sum(page_calls.values()) == 5 + layout.MAX_REDRAWS, page_calls              # 다시 그리기는 실행당 2쪽까지
assert sorted(page_calls.values()) == [1, 1, 1, 2, 2], page_calls
for pi in b8["illustrations"].pages:
    assert pi.status == "completed" and len(pi.text_blocks) == 1, pi                 # 합쳐진 한 덩어리
    tb = pi.text_blocks[0]
    assert (tb.x, tb.y, tb.color) == (5.0, 7.0, "dark") and len(tb.paragraphs) == 2   # 기본 자리, 문단은 그대로
assert 2 in places and 1 in places                                                  # 두 덩어리로 찾고, 합쳐서도 찾았다
assert all(p.path.endswith(f"page-{p.order:02d}.png") for p in b8["illustrations"].pages)
# 8-6) 다시 그리기 프롬프트: 덩어리 크기·자리(where)가 들어가고, 첫 그리기에는 자리 지시가 없다
sizes1 = [layout.block_size(b) for b in layout.build_blocks(["가나다."], [[[0]]])]
assert "left top" in il.layout_prompt(sizes1, ["left top"]) and "left top" not in il.layout_prompt(sizes1)
print("redraw cap / default spot ok:", dict(page_calls))

# 8-7) 두 덩어리는 자리가 없고 합친 한 덩어리는 있으면 합친 걸로 간다 — 다시 그리지 않는다 (settle을 그렇게 흉내 낸다)
one_page = st8.model_copy(update={"pages": st8.pages[:1]})
orig_settle = layout.settle
il.settle = lambda busy, blocks, spots: None if len(blocks) > 1 else orig_settle(busy, blocks, spots)
page_calls.clear()
places.clear()
il.set_image_override(lambda p, refs: (page_calls.update(["x"]) or mock.tiny_png(p, refs)) if refs and "Scene" in p else mock.tiny_png(p, refs))
m = il.illustrate({"story": one_page, "output_prefix": "stories/t/runs/3/"})["illustrations"].pages[0]
il.settle = orig_settle
assert places == [2, 1] and page_calls["x"] == 1, (places, page_calls)           # 합쳐서 찾았고 다시 그리지 않았다
assert len(m.text_blocks) == 1 and len(m.text_blocks[0].paragraphs) == 2          # 문단은 그대로
assert lines_of(m) == joined(one_page.pages[0].text)

# 8-8) 다시 그린 그림이 괜찮으면 같은 key에 덮어쓰고 그 그림에서 자리를 찾는다. 다시 그리기 프롬프트에는 자리 지시가 있다
one_line = one_page.model_copy(update={"pages": [one_page.pages[0].model_copy(update={"text": "한 줄뿐인 글이에요."})]})
sent: list[str] = []
flat = striped_png((0, 0, 100, 100))   # 전부 흰 바탕


def second_is_calm(prompt, refs):
    if refs and "Scene" in prompt:
        sent.append(prompt)
        return striped_png() if len(sent) == 1 else flat
    return mock.tiny_png(prompt, refs)


places.clear()
il.set_image_override(second_is_calm)
m = il.illustrate({"story": one_line, "output_prefix": "stories/t/runs/4/"})["illustrations"].pages[0]
assert len(sent) == 2 and places == [1, 1], (len(sent), places)
assert "left top" not in sent[0] and "left top" in sent[1]
assert storage.read_bytes(m.path) == flat and m.path == "stories/t/runs/4/images/page-01.png"   # 같은 key에 덮어씀
il.place_page = orig_place
il.set_image_override(mock.tiny_png)
llm.set_structured_override(recording_structured)
# 8-9) 쪽 줄 수가 5를 넘으면 경고만 (쪽 번호와 줄 수, 글은 안 남김). 읽지 못하는 그림이어도 기본 자리 text_blocks는 준다
import logging  # noqa: E402

secret = "비밀문장이에요. " * 6
long_page = one_line.model_copy(update={"pages": [one_line.pages[0].model_copy(update={"text": secret})]})
logged: list[str] = []


class Grab(logging.Handler):
    def emit(self, record):
        logged.append(record.getMessage())


h = Grab()
logging.getLogger("firstory.illustrate").addHandler(h)
il.set_image_override(lambda p, refs: b"RIFF\x00\x00\x00\x00WEBPVP8 " if refs and "Scene" in p else mock.tiny_png(p, refs))   # PIL이 못 읽는 그림
m = il.illustrate({"story": long_page, "output_prefix": "stories/t/runs/5/"})["illustrations"].pages[0]
logging.getLogger("firstory.illustrate").removeHandler(h)
assert any("1" in x and "6" in x and "5줄 초과" in x for x in logged), logged
assert not any("비밀문장" in x for x in logged), logged
assert m.status == "completed" and len(m.text_blocks) == 1 and (m.text_blocks[0].x, m.text_blocks[0].y) == (5.0, 7.0), m
assert lines_of(m) == joined(secret)
il.set_image_override(mock.tiny_png)

print("text blocks ok")

print("\nALL OK")
