"""
API 없이 그래프가 끝까지 도는지 확인. (uv run python evals/mock_run.py)
LLM/이미지 호출을 가짜로 바꿔치기한다. 품질 평가가 아니라 배선 확인용.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import sys
import tempfile
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langgraph.types import Command
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstory import lab, llm, mock, server, storage, tts  # noqa: E402
from firstory.config import config  # noqa: E402
from firstory.graph import compile_graph, new_thread_id  # noqa: E402
from firstory.nodes import illustrate as il  # noqa: E402
from firstory.nodes import interview as iv  # noqa: E402
from firstory.nodes import layout  # noqa: E402
from firstory.nodes.story import review_update, scene_note  # noqa: E402
from firstory.schemas import (  # noqa: E402
    AfterReading, BeforeReading, CharacterSheet, GuidePrompt, InterviewTurnResult, PageAudio, ParentUpdate, PolishedPage,
    PolishedStory, ReadingGuide, StoryInputContext, StoryPage, StoryRevision, StoryText, Strategy, TextChunking,
    TextPlacement, TextPlacementWithWord, Turn)

tts.set_tts_override(mock.silent_mp3)   # 진짜 ElevenLabs는 절대 부르지 않는다 (유료 키가 환경에 있어도)

# ── 공용 도우미 ──
_prompts: list[tuple[str, str]] = []   # (node, system) — 전략 블록이 실제로 들어갔는지 확인용


def recording_structured(**kw):
    _prompts.append((kw["node"], kw["system"]))
    return mock.fake_structured(**kw)


def last_prompt(node: str) -> str:
    return [s for n, s in _prompts if n == node][-1]


def recording_llm(sink: list[str], answer):
    """LLM에 넘긴 system 프롬프트를 sink에 모으고 answer로 답한다."""
    def fn(**kw):
        sink.append(kw["system"])
        return answer(**kw)
    return fn


def recording_images(sink: list[str]):
    """그림 프롬프트를 sink에 모으고 가짜 그림을 돌려준다."""
    def draw(prompt, refs):
        sink.append(prompt)
        return mock.tiny_png(prompt, refs)
    return draw


def new_cfg() -> dict:
    return {"configurable": {"thread_id": new_thread_id()}}


def resume(cfg: dict, value):
    return graph.invoke(Command(resume=value), cfg)


def interrupt_of(r: dict) -> dict:
    return r["__interrupt__"][0].value


def node_names(cost) -> list[str]:
    return [c.node for c in cost]


def page_of(pages, order: int):
    return next(p for p in pages if p.order == order)


def by_order(pages) -> dict:
    return {p.order: p for p in pages}


def page_paths(ill) -> dict[int, str]:
    return {pg.order: pg.path for pg in ill.pages}


def joined(s: str) -> str:
    return re.sub(r"\s", "", s)


def raw_lines(pi) -> str:
    return "".join(line for b in pi.text_blocks for para in b.paragraphs for line in para)


def lines_of(pi) -> str:
    return joined(raw_lines(pi))


def last_para(pi) -> list[str]:
    return pi.text_blocks[-1].paragraphs[-1]


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def image_size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


def solid_png(w: int, h: int) -> bytes:
    return png_bytes(Image.new("RGB", (w, h), (240, 200, 210)))


def striped_png(clear=None, gray: int = 40) -> bytes:
    """흰 바탕에 세로 줄무늬(복잡)인 그림. gray는 줄 색, clear=(x0,y0,x1,y1)(%)는 흰 바탕으로 비워 둔다."""
    img = Image.new("RGB", (layout.W, layout.H), "white")
    d = ImageDraw.Draw(img)
    for x in range(0, layout.W, 24):
        d.rectangle([x, 0, x + 11, layout.H], fill=(gray,) * 3)
    if clear:
        x0, y0, x1, y1 = clear
        d.rectangle([x0 / 100 * layout.W, y0 / 100 * layout.H, x1 / 100 * layout.W, y1 / 100 * layout.H], fill="white")
    return png_bytes(img)


def faint_png(diff: int) -> bytes:
    """흰 바탕에 옅은 회색(255-diff) 세로 줄무늬 — 복잡도 ≈ diff × 0.33 (striped_png와 같은 간격)"""
    return striped_png(gray=255 - diff)


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextmanager
def captured_logs():
    """firstory.illustrate 로그 메시지를 모은다."""
    handler = _Grab()
    logger = logging.getLogger("firstory.illustrate")
    logger.addHandler(handler)
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)


def boom(*a, **k):
    raise RuntimeError("글꼴 계산 실패 흉내")


mock.enable()
llm.set_structured_override(recording_structured)
ALL_PAGES = list(range(1, config.page_count + 1))

data = json.loads((ROOT / "datasets/inputs/donggeul.json").read_text(encoding="utf-8"))
data.pop("scripted_answers", None)

graph = compile_graph(ROOT / "out" / "mock-checkpoints.db")

# ── 1) interrupt 경로: 인터뷰 질문 2개 + 마무리 질문 + 생성 전 확인 + 검토 → 재생성(images) → 완료 ──
cfg = new_cfg()
r = graph.invoke({"context": data, "auto_answers": [], "auto_approve": False, "skip_images": False}, cfg)
seen = []
while "__interrupt__" in r:
    p = interrupt_of(r)
    seen.append(p["type"])
    if p["type"] == "interview" and p["question"] == iv.READY_QUESTION:
        assert p["turn"] == 3 and p["choices"] == [iv.READY_MORE, iv.READY_GO], p
        r = resume(cfg, iv.READY_GO)
    elif p["type"] == "interview":
        r = resume(cfg, "답변 " + str(p["turn"]))
    elif p["type"] == "confirm":
        assert p["summary"] and p["situation_summary"] and p["end_reason"] == "sufficient" and p["context"]["parent"], p
        assert graph.get_state(cfg).next == ("confirm_generate",)
        r = resume(cfg, {"action": "generate", "tone": "warm"})
    elif p["type"] == "review":
        if seen.count("review") == 1:
            r = resume(cfg, {"action": "regenerate", "scope": "images", "feedback": "3"})
        else:
            r = resume(cfg, {"action": "approve"})
print("interrupts:", seen)
assert seen == ["interview", "interview", "interview", "confirm", "review", "review"], seen  # images 재생성 → render → review 다시
assert r["status"] == "completed" and len(r["guide"].prompts) == 2 and r["guide"].synopsis
# 장면 설명은 AI가 아니라 코드가 본문 질문을 그대로 인용해 만든다 (#105)
assert [q.scene_note for q in r["guide"].prompts] == [
    "“포포는 어떤 기분이었을까요?”라는 질문으로 아이와 함께 주인공의 마음을 헤아려 볼 수 있어요.",
    "“내일 포포는 뭐라고 말하고 싶을까요?”라는 질문으로 아이와 함께 다음에 일어날 일을 상상해 볼 수 있어요."], r["guide"].prompts
assert scene_note(GuidePrompt(id="q", after_page=3, purpose="empathy",
                              text="성은 무너지고 미루 마음은 **콩콩** 뛰었어요. 미루는 왜 큰소리를 냈을까요?")) \
    == "“미루는 왜 큰소리를 냈을까요?”라는 질문으로 아이와 함께 주인공의 마음을 헤아려 볼 수 있어요."
assert scene_note(GuidePrompt(id="q", after_page=3, purpose="perspective", text="보보는 무슨 생각을 했을까요? 말해 볼까요.")) \
    .startswith("“보보는 무슨 생각을 했을까요?”라는")   # 물음 문장이 끝이 아니어도 물음 문장을 인용
assert "scene_note" not in str(ReadingGuide.model_json_schema())   # AI에게는 쓰라고 하지 않는다
assert r["tone"] == "warm"   # 확인 재개 값의 tone이 state에 남음
nodes = node_names(r["cost"])
assert nodes.count("illustrate:page3") == 2 and nodes.count("illustrate:page1") == 1, nodes  # 3페이지만 다시 그림
assert nodes.count("illustrate:sheet:포포") == 1 and nodes.count("illustrate:sheet:엄마곰") == 1, nodes  # 시트는 재사용
print("run_dir:", r["run_dir"])

# ── 1-2) 재생성 피드백: character는 설계 프롬프트에, images는 "3페이지"·"3, 5쪽"·"p3"에서 쪽 번호만 ──
cfg = new_cfg()
r = graph.invoke({"context": data, "auto_answers": ["a1", "a2"], "auto_confirm": True, "auto_approve": False,
                  "skip_images": False}, cfg)
assert "## 부모 요청" not in last_prompt("design_story")   # 처음 설계엔 요청 블록 없음
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
for cmd in resumes:
    assert interrupt_of(r)["type"] == "review", r.get("__interrupt__")
    before = len(graph.get_state(cfg).values["cost"])
    r = resume(cfg, cmd)
    if cmd.get("scope") == "character":
        design = last_prompt("design_story")
        assert "## 부모 요청" in design and "토끼 말고 공룡으로 바꿔 주세요" in design, design[-300:]
    if cmd.get("scope") == "images":
        new = node_names(graph.get_state(cfg).values["cost"][before:])
        redrawn.append(sorted(int(n.removeprefix("illustrate:page")) for n in new if n.startswith("illustrate:page")))
assert r["status"] == "completed"
assert redrawn == [[3], [3, 5], [3], ALL_PAGES, [3]], redrawn   # 숫자 없으면 기존대로 전부
print("regen feedback ok:", redrawn)

# ── 1-3) 실행별 결과물 경로 (G3·G4): Spring이 실행마다 새 output_prefix를 준다 ──
base = f"mock-stories/{new_thread_id()}/runs"
cfg = new_cfg()
r = graph.invoke({"context": data, "auto_answers": ["a1", "a2"], "auto_approve": False, "skip_images": False}, cfg)
assert interrupt_of(r)["question"] == iv.READY_QUESTION   # auto_confirm이 아니면 마무리 질문은 사람이 답한다
r = resume(cfg, iv.READY_GO)
assert interrupt_of(r)["type"] == "confirm"
r = resume(cfg, {"action": "generate", "output_prefix": f"{base}/1/"})
ill1 = graph.get_state(cfg).values["illustrations"]
assert all(pg.path == f"{base}/1/images/page-{pg.order:02d}.png" for pg in ill1.pages), ill1.pages
assert all(k.startswith(f"{base}/1/images/sheet-") for k in ill1.character_sheets.values())
assert storage.exists(f"{base}/1/03-story.json") and storage.exists(f"{base}/1/book.html")
# 쪽마다 음성 (6장): 첫 실행은 전부 새로 만들고, 덤프에도 남는다
st1 = graph.get_state(cfg).values
nar1 = st1["narration"]
assert [p.path for p in nar1.pages] == [f"{base}/1/audio/page-{i:02d}.mp3" for i in ALL_PAGES], nar1.pages
assert "narrate:page1" in node_names(st1["cost"])
assert storage.exists(f"{base}/1/06-narration.json")
assert server._page(st1["story"].pages[0], None, None)["audio_path"] is None   # 음성 없는 동화
assert server._page(st1["story"].pages[0], None, None)["audio_status"] is None
_failed = server._page(st1["story"].pages[0], None, PageAudio(order=1, status="failed"))   # 음성 실패한 쪽
assert (_failed["audio_path"], _failed["audio_status"]) == (None, "failed")
assert nar1.speakers is not None and all(pa.text_hash for pa in nar1.pages)   # 글만 다시 만들 때 쓰는 값
assert r["run_dir"] == str(storage.local_path(f"{base}/1/"))

# 그림만 다시(3쪽) → 3쪽만 runs/2에 새로. 나머지 쪽과 시트는 runs/1의 key 그대로, 파일 복사 없음
n_before = len(graph.get_state(cfg).values["cost"])
r = resume(cfg, {"action": "regenerate", "scope": "images", "feedback": "3", "output_prefix": f"{base}/2/"})
st2 = graph.get_state(cfg).values
assert st2["narration"] == nar1 and not any(n.startswith("narrate:") for n in node_names(st2["cost"][n_before:]))   # 그림만 다시: 음성은 건드리지 않는다
ill2 = graph.get_state(cfg).values["illustrations"]
assert page_paths(ill2)[3] == f"{base}/2/images/page-03.png"
assert all(pg.path == f"{base}/1/images/page-{pg.order:02d}.png" for pg in ill2.pages if pg.order != 3)
assert ill2.character_sheets == ill1.character_sheets
assert not storage.exists(f"{base}/2/images/page-01.png") and not any(
    storage.exists(f"{base}/2/images/{Path(k).name}") for k in ill1.character_sheets.values())
assert storage.exists(f"{base}/1/images/page-03.png")   # 이전 실행 파일은 남는다
book = storage.local_path(f"{base}/2/book.html").read_text(encoding="utf-8")
assert 'src="../1/images/page-01.png"' in book and 'src="images/page-03.png"' in book
assert 'data-label="앞표지"><div class="scene book-cover"><img src="../1/images/cover.png"' in book and 'data-label="뒤표지"' in book   # 앞표지 = 정사각형 (#88, #122, #125)

# 글 다시 → mock 작가가 1쪽만 고쳐 그 쪽 장면이 바뀐다. 1쪽 그림만 runs/3에 새로, 나머지 쪽과 시트는 v2의 key 그대로
n_before = len(graph.get_state(cfg).values["cost"])
resume(cfg, {"action": "regenerate", "scope": "text", "feedback": "더 짧게", "output_prefix": f"{base}/3/"})
st3 = graph.get_state(cfg).values
nar3 = st3["narration"]
assert [p.path for p in nar3.pages] == [p.path for p in nar1.pages]   # 같은 글이면 이전 key 재사용
assert not any(n.startswith("narrate:") for n in node_names(st3["cost"][n_before:])), node_names(st3["cost"][n_before:])
ill3 = graph.get_state(cfg).values["illustrations"]
paths2, paths3 = page_paths(ill2), page_paths(ill3)
assert paths3[1] == f"{base}/3/images/page-01.png"
assert all(paths3[o] == paths2[o] for o in paths3 if o != 1), paths3
assert ill3.character_sheets == ill1.character_sheets
assert storage.exists(f"{base}/2/images/page-03.png") and storage.exists(f"{base}/1/03-story.json")
r = resume(cfg, {"action": "approve"})
assert r["status"] == "completed"

for bad in ["../x.png", "/abs/x.png", "a\\b.png", "c:/x.png", f"{base}/../../x.png"]:   # 저장소 밖 key는 거부
    try:
        storage.write_bytes(bad, b"x")
        raise AssertionError(f"거부 안 됨: {bad}")
    except ValueError:
        pass
print("run paths ok:", base)

# ── 2) --auto 경로: scripted answers + auto_approve + 병렬 fan-in ──
r2 = graph.invoke({"context": data, "auto_answers": ["a1", "a2"], "auto_confirm": True, "auto_approve": True,
                   "skip_images": False}, new_cfg())
assert "__interrupt__" not in r2
assert r2["status"] == "completed" and r2["guide"] is not None and r2["illustrations"] is not None
assert len(r2["interview_turns"]) == 2 and r2["interview_done_by"] == "sufficient"
assert all(p.status == "completed" for p in r2["illustrations"].pages)
out = Path(r2["run_dir"])
assert (out / "book.html").exists() and (out / "images" / f"page-{config.page_count:02d}.png").exists()
assert len(r2["illustrations"].character_sheets) == 2
print("auto ok:", out, "cost entries:", len(r2["cost"]))

# ── 3) 재개: 인터뷰 중간에 멈춘 thread를 get_state 로 보고 이어가기 ──
cfg = new_cfg()
r3 = graph.invoke({"context": data, "auto_answers": [], "auto_approve": True, "skip_images": True}, cfg)
assert "__interrupt__" in r3
assert graph.get_state(cfg).next == ("interview_answer",), graph.get_state(cfg).next
r3 = resume(cfg, "skip")      # user_skip 경로 → 생성 전 확인에서 멈춤
assert interrupt_of(r3)["type"] == "confirm" and interrupt_of(r3)["end_reason"] == "user_skip"
assert graph.get_state(cfg).values["status"] == "requested"   # 확인 전에는 아직 생성 시작 아님
r3 = resume(cfg, {})          # LangGraph는 빈 값을 재개로 안 침 → 그대로 멈춰 있음
assert interrupt_of(r3)["type"] == "confirm"
r3 = resume(cfg, {"action": "generate"})   # tone 없이 재개
assert r3["interview_done_by"] == "user_skip" and r3["status"] == "completed"
assert r3.get("tone") is None
assert r3["context"].parent.message_direction == "undecided"
assert not any("## 전략" in s for n, s in _prompts if n == "design_story")   # 전략을 안 켜면 지금 프롬프트 그대로
print("resume/skip ok")

# ── 4) 프롬프트 전략 전부 켜기: 설계에 전략 블록이 붙고 칸이 늘어난다 ──
r4 = graph.invoke({"context": data, "auto_answers": ["a1", "a2"], "auto_confirm": True, "auto_approve": True,
                   "skip_images": True,
                   "strategy": Strategy(arc=True, engine=True, fewshot=True, motif=True)}, new_cfg())
assert r4["story_design"].want and r4["story_design"].refrain.line == "쓱쓱!"
nodes4 = node_names(r4["cost"])
assert nodes4.count("design_story") == 1, nodes4
design = last_prompt("design_story")
assert all(f"## 전략: {t}" in design for t in ("상황별 감정 흐름", "이야기 엔진", "반복 문구", "좋은 설계 예시"))
assert "### 다시 같이 놀기" in design   # donggeul = friend_conflict
assert "### 전략: 이야기 엔진" in last_prompt("write_story")
print("strategy ok")

# ── 5) 프롬프트 실험: 기준 실행(2번)의 인터뷰로 전략마다 텍스트만 뽑고 채점 ──
exp = lab.run_experiment(out, list(lab.PRESETS), judge_on=True, workers=3, root=Path(tempfile.mkdtemp()))
e = lab.load(exp)
assert all(v["story"] and v["judge"] and not v["error"] for v in e["variants"].values()), {k: v["error"] for k, v in e["variants"].items()}
assert "attempts" in e["variants"]["engine"]["design"] and "attempts" not in e["variants"]["base"]["design"]
assert lab.score_row(e["variants"]["all"])["설계 반영"] == "4/5"
assert "| 기본 |" in (exp / "compare.md").read_text(encoding="utf-8")
print("lab ok:", exp)

# ── 6) 표지: 전부 그릴 때 그리고, 글 다시 만들기에서 제목이 그대로면 재사용, 제목만 바뀌면 표지만. 실패하면 None ──
il.set_image_override(mock.tiny_png)
st = StoryText(title="A", characters=[CharacterSheet(name="포포", role="protagonist", visual_description="rabbit")],
               style_guide="s", pages=[StoryPage(order=i, text="t", characters_in_scene=["포포"], image_prompt="p") for i in (1, 2)])
c1 = il.illustrate({"story": st, "output_prefix": "stories/c/runs/1/"})["illustrations"]
assert c1.cover == "stories/c/runs/1/images/cover.png" and c1.cover_title == "A"
# 처음: 앞표지는 따로 그리지 않고 정사각형 표지 key, 뒤표지는 이번 실행 key (#88, #125)
assert c1.front_cover == c1.cover and c1.back_cover == "stories/c/runs/1/images/back-cover.png"
assert sorted(n for n in node_names(il.illustrate({"story": st, "output_prefix": "stories/c/runs/9/"})["cost"])
              if "cover" in n) == ["illustrate:back_cover", "illustrate:cover"]
# 뒤표지는 정사각형 표지와 같은 크기 (#125)
sizes = {}
orig_edit = il._edit


def size_spy(prompt, refs, size=None):
    sizes.setdefault(prompt.split(". ")[0], size)
    return orig_edit(prompt, refs, size=size)


with patch.object(il, "_edit", size_spy):
    il.illustrate({"story": st, "output_prefix": "stories/c/runs/14/"})
assert sizes["Back cover of a children's picture book"] == config.cover_size == "1024x1024", sizes
# 뒤표지는 시트만 참고
ref_counts = {}


def count_refs(prompt, refs):
    ref_counts.setdefault(prompt.split(". ")[0], len(refs))
    return mock.tiny_png(prompt, refs)


il.set_image_override(count_refs)
il.illustrate({"story": st, "output_prefix": "stories/c/runs/8/"})
assert ref_counts["Back cover of a children's picture book"] == len(st.characters), ref_counts
# 뒤표지는 빈 바탕에 주인공 혼자 작게: 등장인물이 여럿이어도 주인공 시트만, 마지막 장면은 넣지 않는다
back_prompts: list[tuple[str, int]] = []


def back_spy(prompt, refs):
    if prompt.startswith("Back cover"):
        back_prompts.append((prompt, len(refs)))
    return mock.tiny_png(prompt, refs)


il.set_image_override(back_spy)
st_two = st.model_copy(update={"characters": st.characters + [CharacterSheet(name="곰", role="supporting", visual_description="bear")]})
il.illustrate({"story": st_two, "output_prefix": "stories/c/runs/13/"})
assert len(back_prompts) == 1 and back_prompts[0][1] == 1, back_prompts
assert "포포" in back_prompts[0][0] and "곰" not in back_prompts[0][0] and "Last scene" not in back_prompts[0][0], back_prompts[0][0]
il.set_image_override(mock.tiny_png)
unchanged = il.illustrate({"story": st, "illustrations": c1, "redraw_pages": [], "output_prefix": "stories/c/runs/2/"})
assert unchanged["illustrations"] is c1 and unchanged["cost"] == []
retitled = il.illustrate({"story": st.model_copy(update={"title": "B"}), "illustrations": c1, "redraw_pages": [],
                          "output_prefix": "stories/c/runs/3/"})
rt = retitled["illustrations"]
assert rt.cover == "stories/c/runs/3/images/cover.png" and rt.cover_title == "B"
assert [p.path for p in rt.pages] == [p.path for p in c1.pages]
# 제목만 바뀜: 정사각형 새로(앞표지도 그 key), 뒤표지는 이전
assert rt.front_cover == "stories/c/runs/3/images/cover.png"
assert rt.back_cover == c1.back_cover
assert sorted(node_names(retitled["cost"])) == ["illustrate:cover"], retitled["cost"]


# 정사각형만 실패(두 번 다) → 앞표지도 없음 (따로 그리지 않는다, #125), 뒤표지는 그려짐
def no_square(prompt, refs):
    if prompt.startswith("Front cover"):
        raise RuntimeError("정사각형 실패 흉내")
    return mock.tiny_png(prompt, refs)


il.set_image_override(no_square)
r = il.illustrate({"story": st, "output_prefix": "stories/c/runs/5/"})
assert r["illustrations"].cover is None and r["illustrations"].front_cover is None
assert r["illustrations"].back_cover == "stories/c/runs/5/images/back-cover.png"

# 표지가 한 번 실패하면 한 번 더 그린다
back_tries: list[str] = []


def flaky_back(prompt, refs):
    if prompt.startswith("Back cover"):
        back_tries.append(prompt)
        if len(back_tries) == 1:
            raise RuntimeError("한 번 실패")
    return mock.tiny_png(prompt, refs)


il.set_image_override(flaky_back)
assert il.illustrate({"story": st, "output_prefix": "stories/c/runs/6/"})["illustrations"].back_cover and len(back_tries) == 2
il.set_image_override(mock.tiny_png)

# 앞·뒤표지가 없는 이전 실행(배포 전 동화) + 글 다시(장면·제목 그대로) → 뒤표지만 그리고 앞표지는 정사각형 key
old = c1.model_copy(update={"front_cover": None, "back_cover": None})
upgraded = il.illustrate({"story": st, "illustrations": old, "redraw_pages": [], "output_prefix": "stories/c/runs/7/"})
assert sorted(node_names(upgraded["cost"])) == ["illustrate:back_cover"], upgraded["cost"]
assert upgraded["illustrations"].front_cover == c1.cover
# 가로 앞표지가 있는 이전 실행(#125 전 동화) + 글 다시 → 아무것도 안 그리고 앞표지만 정사각형 key로
wide = c1.model_copy(update={"front_cover": "stories/c/runs/1/images/front-cover.png"})
w = il.illustrate({"story": st, "illustrations": wide, "redraw_pages": [], "output_prefix": "stories/c/runs/15/"})
assert w["cost"] == [] and w["illustrations"].front_cover == c1.cover and w["illustrations"].back_cover == c1.back_cover
assert upgraded["illustrations"].cover == c1.cover and [p.path for p in upgraded["illustrations"].pages] == [p.path for p in c1.pages]

# 그림만 다시(일부 쪽): 마지막 쪽(2)을 다시 그려도 표지 셋 그대로 (뒤표지는 마지막 장면과 상관없다, #90)
for only in ({1}, {2}):
    pp, pc = il._run(st, f"stories/c/runs/1{min(only)}/images", only_pages=only, prev=c1)
    assert (pp.cover, pp.front_cover, pp.back_cover) == (c1.cover, c1.front_cover, c1.back_cover), only
    assert not any("cover" in n for n in node_names(pc)), pc


def no_cover(prompt, refs):
    if "Front cover" in prompt:
        raise RuntimeError("표지 실패 흉내")
    return mock.tiny_png(prompt, refs)


il.set_image_override(no_cover)
failed = il.illustrate({"story": st, "output_prefix": "stories/c/runs/4/"})["illustrations"]
assert failed.cover is None and failed.cover_title is None and all(p.status == "completed" for p in failed.pages)
assert failed.front_cover is None and failed.back_cover   # 정사각형이 없으면 앞표지도 없다 (#125). 뒤표지는 그린다
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
assert node_names(blocked["cost"]).count("illustrate:soften") == 2
assert blocked["illustrations"].cover                                                      # 다른 그림은 그대로
il.set_image_override(mock.tiny_png)
print("policy retry ok")

# ── 지시문에 이어지는 동작(then·next part)이 있으면 그리기 전에 한 순간으로 다시 쓴다 (#110). 'next to'는 그대로 ──
moment_prompts: list[str] = []
il.set_image_override(recording_images(moment_prompts))
st4 = st.model_copy(update={"pages": [StoryPage(order=1, text="t", characters_in_scene=["포포"], image_prompt="push-a, then hand-b"),
                                      StoryPage(order=2, text="t", characters_in_scene=["포포"], image_prompt="sit next to bear")]})
mo = il.illustrate({"story": st4, "output_prefix": "stories/c/runs/13/"})
scenes = [x for x in moment_prompts if "Scene (" in x]
assert any("one moment: push-a, and hand-b" in x for x in scenes) and not any("then hand-b" in x for x in scenes), scenes
assert any("precisely): sit next to bear\n" in x for x in scenes), scenes
assert node_names(mo["cost"]).count("illustrate:one_moment") == 1
assert il.SEQUENCE.search("In the next part of the same single scene") and not il.SEQUENCE.search("Sol sits next to the stroller")
il.set_image_override(mock.tiny_png)
print("one moment ok")

# ── 시트·쪽·표지는 받은 형식대로 key 확장자를 정한다 (#32, #80) ──
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "


def webp_all(prompt, refs):
    return WEBP


il.set_image_override(webp_all)
webp_ill = il.illustrate({"story": st, "output_prefix": "stories/c/runs/6/"})["illustrations"]
assert [p.path for p in webp_ill.pages] == ["stories/c/runs/6/images/page-01.webp", "stories/c/runs/6/images/page-02.webp"]
assert webp_ill.cover == "stories/c/runs/6/images/cover.webp"
assert webp_ill.character_sheets and all(k.startswith("stories/c/runs/6/images/sheet-") and k.endswith(".webp")
                                         for k in webp_ill.character_sheets.values()), webp_ill.character_sheets
il.set_image_override(mock.tiny_png)
print("webp ok")

# ── 실제 호출 인자: 시트는 SHEET_SIZE·IMAGE_FORMAT, 첨부 MIME은 실제 형식 (#80) ──
api_calls: list[tuple[str, dict]] = []


class _FakeImages:
    def _answer(self, kind: str, kw: dict):
        api_calls.append((kind, kw))
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(WEBP).decode())], usage=None)

    def generate(self, **kw):
        return self._answer("generate", kw)

    def edit(self, **kw):
        return self._answer("edit", kw)


png_sheet = mock.tiny_png("", [])
il.set_image_override(None)
with patch.object(il, "client", lambda: SimpleNamespace(images=_FakeImages())):
    assert il._gen("sheet")[0] == WEBP
    assert il._edit("page", [("포포.png", WEBP), ("엄마곰.png", png_sheet)])[0] == WEBP
il.set_image_override(mock.tiny_png)
(_, g), (_, e) = api_calls
assert g["size"] == config.sheet_size == "1024x1024", g
assert g.get("output_format") == config.image_format == "webp", g
assert e["image"] == [("포포.webp", WEBP, "image/webp"), ("엄마곰.png", png_sheet, "image/png")], e["image"]
print("sheet size/format ok")

# ── 쪽·표지에 첨부하는 시트는 긴 변 1024px로 줄인다. 저장된 시트는 그대로 (#67) ──
ref_sizes: list[tuple[int, int]] = []


def big_sheets(prompt, refs):
    if not refs:                       # 예전 시트(generate)처럼 쪽 그림 크기로 만든다
        return solid_png(1920, 1088)
    ref_sizes.extend(image_size(r) for r in refs)
    return mock.tiny_png(prompt, refs)


il.set_image_override(big_sheets)
r1024 = il.illustrate({"story": st, "output_prefix": "stories/c/runs/8/"})["illustrations"]
assert ref_sizes and all(max(sz) <= config.ref_max_side for sz in ref_sizes), ref_sizes       # 쪽·표지 첨부는 1024 이하
assert max(ref_sizes) == (1024, 580), ref_sizes                                                # 비율 유지
assert image_size(storage.read_bytes(r1024.character_sheets["포포"])) == (1920, 1088)          # 저장 시트는 원본
square = solid_png(1024, 1024)        # 지금 시트(SHEET_SIZE) 크기는 줄이지 않고 그대로 첨부 (#80)
assert il._ref(square) is square
small = mock.tiny_png("", [])
assert il._ref(small) is small and il._ref(b"not an image") == b"not an image"               # 작거나 못 읽으면 그대로
il.set_image_override(mock.tiny_png)
print("ref sheet 1024 ok")

# ── 그림만 다시: 쪽 선택(regenerate_pages)과 부모 메모(review_feedback)를 따로 (#46) ──
memo_prompts: list[str] = []
il.set_image_override(recording_images(memo_prompts))
memo_state = {"story": st, "illustrations": c1, "output_prefix": "stories/c/runs/7/"}
memo = "2쪽 포포가 더 활짝 웃게 해 주세요"
o = il.illustrate_only(memo_state | {"regenerate_pages": [1], "review_feedback": memo})   # 메모의 "2쪽"이 아니라 고른 쪽만
assert [n for n in node_names(o["cost"]) if n.startswith("illustrate:")] == ["illustrate:page1"], o["cost"]
assert len(memo_prompts) == 1 and memo in memo_prompts[0] and "Parent's request" in memo_prompts[0]
memo_prompts.clear()
o = il.illustrate_only(memo_state | {"regenerate_pages": [], "review_feedback": memo})       # []는 전부, 메모는 쪽마다
assert sorted(n for n in node_names(o["cost"]) if n.startswith("illustrate:page")) == ["illustrate:page1", "illustrate:page2"]
assert all(memo in p for p in memo_prompts if "Scene" in p) and not any(memo in p for p in memo_prompts if "Front cover" in p)
memo_prompts.clear()
o = il.illustrate_only(memo_state | {"regenerate_pages": [2], "review_feedback": None})      # 메모 없으면 프롬프트 그대로
assert len(memo_prompts) == 1 and "Parent's request" not in memo_prompts[0]   # 마지막 쪽이어도 뒤표지는 그대로 (#90)
memo_prompts.clear()
o = il.illustrate_only(memo_state | {"review_feedback": "2"})                                # CLI·뷰어: 쪽 번호만이면 메모 아님
assert [n for n in node_names(o["cost"]) if n.startswith("illustrate:")] == ["illustrate:page2"] and "Parent's request" not in memo_prompts[0]
assert il._memo("3, 5쪽") is None and il._memo(" ") is None and il._memo(memo) == memo
assert review_update({"action": "regenerate", "scope": "images", "pages": [], "feedback": memo})["regenerate_pages"] == []
assert review_update({"action": "regenerate", "scope": "text", "pages": [3], "feedback": "x"})["regenerate_pages"] is None
il.set_image_override(mock.tiny_png)
print("image regen memo ok")

# ── 인터뷰 상한(15)과 반복: 몇 턴 전 질문으로 돌아가도 끝내고, 15턴째에는 max_turns ──
assert config.max_interview_turns == 15
ctx0 = StoryInputContext.model_validate(data)
asked = [Turn(question=f"질문 {i}번째는 무엇인가요?", answer=f"답 {i}") for i in range(1, 4)]   # 같은 답이면 #20 안전장치가 먼저 끝낸다


def asks(question):
    return lambda **kw: InterviewTurnResult(context_update=ParentUpdate(), status="ask", next_question=question,
                                            choices=["예"], reason="r")


def says_sufficient(**kw):
    return InterviewTurnResult(context_update=ParentUpdate(), status="sufficient", reason="r")


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
llm.set_structured_override(says_sufficient)
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
deepen_prompts: list[str] = []
llm.set_structured_override(recording_llm(deepen_prompts, asks("그때 아이를 안아 줬을 때 아이는 어떤 표정이었어요?")))
for more_answer in (iv.READY_MORE, "네", "있어요!"):   # 칸이 다 채워졌어도 AI가 고른 구체화 질문과 카드
    o = iv.interview_step({"context": done, "interview_turns": asked + [Turn(question=iv.READY_QUESTION, answer=more_answer)]})
    assert o["pending_question"] == "그때 아이를 안아 줬을 때 아이는 어떤 표정이었어요?" and o["pending_choices"] == ["예"], o
    assert "## 이번 턴: 부모가 마무리 확인에서 더 이야기하고 싶다고 했다" in deepen_prompts[-1]
iv.interview_step({"context": ctx0, "interview_turns": asked})
assert "{{deepen}}" not in deepen_prompts[-1] and "## 이번 턴" not in deepen_prompts[-1]   # 평소에는 안 붙는다
llm.set_structured_override(says_sufficient)
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

finish_prompts: list[str] = []
llm.set_structured_override(recording_llm(finish_prompts, mock.fake_structured))
iv.interview_finish({"context": done, "interview_turns": asked + [
    Turn(question=iv.READY_QUESTION, answer="사실 동생이 생겨서 더 예민해요"), Turn(question=iv.READY_QUESTION, answer=iv.READY_GO)]})
assert "동생이 생겨서" in finish_prompts[-1] and iv.READY_GO not in finish_prompts[-1]   # '만들러 갈게요'는 요약에 안 넘김

# ── 필수 칸이 차도 구체화 질문, 상한은 마무리 질문 전 4번·뒤 2번 (#73) ──
deep_prompts: list[str] = []
deep_q = "그럴 때 아이에게 어떤 말을 해 주고 싶으세요?"
llm.set_structured_override(recording_llm(deep_prompts, asks(deep_q)))
four = asked + [Turn(question="넷째로 여쭤볼게요, 아이는 어땠나요?", answer="답 4")]
o = iv.interview_step({"context": done, "interview_turns": asked})          # 칸은 찼지만 답 3번 → AI가 더 묻는다
assert o["pending_question"] == deep_q and o["pending_choices"] == ["예"] and "interview_done_by" not in o, o
assert "부모가 지금까지 답한 질문 수 (마무리 확인 빼고): 3" in deep_prompts[-1]
o = iv.interview_step({"context": done, "interview_turns": four})           # 답 4번 → 마무리 질문
assert o["pending_question"] == iv.READY_QUESTION and o["pending_choices"] == [iv.READY_MORE, iv.READY_GO], o
assert iv.interview_step({"context": ctx0, "interview_turns": four})["pending_question"] == deep_q   # 칸이 비었으면 상한 없음
yes = four + [Turn(question=iv.READY_QUESTION, answer=iv.READY_MORE)]
assert iv.interview_step({"context": done, "interview_turns": yes})["pending_question"] == deep_q            # '네' 뒤 첫 질문
one = yes + [Turn(question="그때 아이 표정은 어땠어요?", answer="울먹였어요")]
assert iv.interview_step({"context": done, "interview_turns": one})["pending_question"] == deep_q            # 1번 답한 뒤 한 번 더
two_more = one + [Turn(question="아이가 뭐라고 했나요?", answer="엄마 가지 마")]
assert iv.interview_step({"context": done, "interview_turns": two_more})["pending_question"] == iv.READY_QUESTION   # 2번이면 다시 마무리
assert "부모가 지금까지 답한 질문 수 (마무리 확인 빼고): 6" in deep_prompts[-1]
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
ready_after_two = {"context": ctx0, "interview_turns": two, "pending_question": iv.READY_QUESTION}
o = iv.interview_answer(ready_after_two | {"auto_answers": [same]})
assert o["interview_done_by"] == "sufficient" and o["interview_turns"][-1].answer == same, o   # 마무리 질문에 같은 답 = 새 이야기 없음
o = iv.interview_answer(ready_after_two | {"auto_answers": ["skip"]})
assert o["interview_turns"][-1].answer == "[skip]"
llm.set_structured_override(recording_structured)
print("repeated answer ok")

# ── 8) 글 덩어리 배치 (text_blocks): 쪽 그림마다 덩어리·자리를 정해 PageImage에 싣는다 ──
# 8-1) 처음 만들기: 그림이 있는 모든 쪽에 덩어리 1~2개, 줄을 이으면 원문. 가이드 질문 쪽은 원문 + 맨 밑 문단에 질문 (#100)
q_by_page = {}
for q in r2["guide"].prompts:
    q_by_page.setdefault(q.after_page, []).append(q.text)
assert q_by_page, r2["guide"]
for pg in r2["story"].pages:
    pi = page_of(r2["illustrations"].pages, pg.order)
    assert pi.text_blocks and 1 <= len(pi.text_blocks) <= 2, pi
    assert lines_of(pi) == joined(pg.text + "".join(q_by_page.get(pg.order, []))), (lines_of(pi), pg.text)
    if pg.order in q_by_page:
        assert joined("".join(last_para(pi))) == joined("".join(q_by_page[pg.order])), pi.text_blocks
    assert all(b.color in ("dark", "light") and 0 <= b.x <= 100 and 0 <= b.y <= 100 for b in pi.text_blocks)
edges = {(e.source, e.target) for e in graph.get_graph().edges}
assert ("reading_guide", "illustrate") in edges and ("polish_story", "illustrate") not in edges, edges   # 가이드가 그림보다 먼저
assert ("polish_story", "safety_output") in edges and ("safety_output", "render") in edges, edges
n2 = node_names(r2["cost"])
assert all(f"layout:place:page{o}" in n2 for o in ALL_PAGES) and "layout:chunk" not in n2 and "layout:place" not in n2, n2
assert "layout:chunk:page1" in n2   # 줄이 둘이라 덩어리 나누기를 부른다

# 8-2) 1×1 가짜 그림(단색)에서도 mock 자리(x 5, y 7)가 settle을 통과한다
assert layout.settle(layout.Busy(mock.tiny_png("", [])), [[["가나다.", "라마바."]]],
                     [{"x": 5, "y": 7, "color": "dark"}]) == [{"x": 5.0, "y": 7.0, "color": "dark"}]

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
cfg = new_cfg()
il.set_image_override(mock.tiny_png)
r8 = graph.invoke({"context": data, "auto_answers": ["a1", "a2"], "auto_confirm": True, "auto_approve": False,
                   "skip_images": False}, cfg)
assert interrupt_of(r8)["type"] == "review"
v1 = graph.get_state(cfg).values
first = page_of(v1["story"].pages, 1)


def text_only_1(**kw):
    if kw["schema"] is StoryRevision:   # 장면(image_prompt·characters_in_scene·text_position)은 첫 원고와 같게
        return StoryRevision(reason="mock", pages=[first.model_copy(update={"text": "1페이지. 포포는 천천히 걸었어요. 바람이 불었어요."})])
    if kw["schema"] is PolishedStory:   # 다듬기는 다시 쓴 쪽(1쪽)만 받는다
        return PolishedStory(pages=[PolishedPage(order=1, text="1쪽. 포포는 천천히 걸었어요. 바람이 불었어요.")])
    return recording_structured(**kw)


llm.set_structured_override(text_only_1)
calls8: list[str] = []
il.set_image_override(recording_images(calls8))
before = len(v1["cost"])
resume(cfg, {"action": "regenerate", "scope": "text", "feedback": "1쪽 글만"})
v2 = graph.get_state(cfg).values
pages1, pages2 = by_order(v1["illustrations"].pages), by_order(v2["illustrations"].pages)
assert not any("Scene" in p for p in calls8), "장면이 같은데 그림을 다시 그렸다"
assert pages2[1].path == pages1[1].path                                        # 그림 key 그대로
new_text = page_of(v2["story"].pages, 1).text
assert "천천히" in new_text and new_text != first.text and lines_of(pages2[1]) == joined(new_text), (new_text, pages2[1].text_blocks)   # 다듬기 뒤 최종 글
assert lines_of(pages1[1]) != lines_of(pages2[1])
assert all(pages2[o].text_blocks == pages1[o].text_blocks for o in pages1 if o != 1)   # 글 그대로인 쪽은 다시 안 함
new_nodes = node_names(v2["cost"][before:])
assert "layout:place:page1" in new_nodes and not any(n.startswith("layout:") and n.endswith(tuple(f"page{o}" for o in range(2, 20)))
                                                      for n in new_nodes), new_nodes
assert not any(n.startswith("illustrate:page") for n in new_nodes)

# 글 다시 만들기에서 가이드가 질문을 다른 쪽으로 옮기면, 두 쪽 모두 그림은 그대로 두고 글 자리만 다시 (#100)
g_old = v2["guide"]
old_q = g_old.prompts[0]
src, dst = old_q.after_page, old_q.after_page + 1
moved = g_old.model_copy(update={"prompts": [old_q.model_copy(update={"after_page": dst}), *g_old.prompts[1:]]})
page1_v2 = page_of(v2["story"].pages, 1)


def move_q(**kw):
    if kw["schema"] is StoryRevision:
        return StoryRevision(reason="mock", pages=[page1_v2])   # 글은 그대로
    if kw["schema"] is PolishedStory:
        return PolishedStory(pages=[PolishedPage(order=1, text=page1_v2.text)])
    if kw["node"] == "reading_guide":
        return moved
    return recording_structured(**kw)


llm.set_structured_override(move_q)
before = len(v2["cost"])
resume(cfg, {"action": "regenerate", "scope": "text", "feedback": "질문만"})
v3 = graph.get_state(cfg).values
pages3 = by_order(v3["illustrations"].pages)
assert pages3[src].path == pages2[src].path and pages3[dst].path == pages2[dst].path      # 그림 그대로
assert joined(old_q.text) not in lines_of(pages3[src]), pages3[src].text_blocks
assert joined("".join(last_para(pages3[dst]))) == joined(old_q.text), pages3[dst].text_blocks
nodes_m = node_names(v3["cost"][before:])
assert f"layout:place:page{src}" in nodes_m and f"layout:place:page{dst}" in nodes_m, nodes_m
assert not any(n.startswith("illustrate:page") for n in nodes_m), nodes_m
llm.set_structured_override(recording_structured)

# 글 자리(text_position)만 바뀐 수정은 장면이 그대로라 그림을 하나도 다시 그리지 않는다
cur1 = page_of(v3["story"].pages, 1)
flip = "bottom" if cur1.text_position == "top" else "top"


def flip_only(**kw):
    if kw["schema"] is StoryRevision:
        return StoryRevision(reason="mock", pages=[first.model_copy(update={"text_position": flip})])
    return recording_structured(**kw)


llm.set_structured_override(flip_only)
calls8.clear()
resume(cfg, {"action": "regenerate", "scope": "text", "feedback": "자리만"})
assert not any("Scene" in p for p in calls8), "text_position만 바뀌었는데 그림을 다시 그렸다"
il.set_image_override(mock.tiny_png)
llm.set_structured_override(recording_structured)
print("text regen relayouts reused image ok")


# 8-5) 두 덩어리가 자리를 못 찾으면: 합쳐서 찾기 → 다시 그리기(실행당 2쪽까지) → 나눈 자리·합친 자리 중 덜 복잡한 곳 (#95)
def two_blocks(**kw):   # 첫 줄 / 나머지 두 덩어리로 나누고 둘 다 같은 자리(5,7)를 달라고 한다 → 겹쳐서 settle이 찾기를 해야 한다
    if kw["schema"] is TextChunking:
        n = len(re.findall(r"^\d+: ", kw["system"], re.M))
        return TextChunking(blocks=[[[0]], [list(range(1, n))]] if n > 1 else [[[0]]])
    return mock.fake_structured(**kw)


places: list[int] = []   # place_page가 받은 덩어리 수
orig_place = layout.place_page


def spy_place(image, blocks, *a, **kw):
    places.append(len(blocks))
    return orig_place(image, blocks, *a, **kw)


il.place_page = spy_place   # 8-8 끝까지 쓴다
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
calm_busy = layout.Busy(striped_png())
for pg, pi in zip(st8.pages, b8["illustrations"].pages):
    lines8 = layout.split_lines(pg.text)
    want_bl, want = layout.calmest_pick(calm_busy, layout.build_blocks(lines8, [[[0]], [list(range(1, len(lines8)))]]))
    assert pi.status == "completed", pi
    assert [tb.paragraphs for tb in pi.text_blocks] == want_bl, (pi.text_blocks, want_bl)
    assert [(tb.x, tb.y, tb.color) for tb in pi.text_blocks] == [(w["x"], w["y"], w["color"]) for w in want], (pi.text_blocks, want)   # 기본 자리 말고 가장 조용한 곳 (#71)
    if len(pi.text_blocks) == 2:
        assert pi.text_blocks[0].x < 50 <= pi.text_blocks[1].x, pi.text_blocks      # 나누면 1 은 왼쪽, 2 는 오른쪽 면
assert 2 in places and 1 in places                                                  # 두 덩어리로 찾고, 합쳐서도 찾았다
assert all(p.path.endswith(f"page-{p.order:02d}.png") for p in b8["illustrations"].pages)
# 8-6) 다시 그리기 프롬프트: 덩어리 크기·자리(where)가 들어가고, 첫 그리기에는 자리 지시가 없다
sizes1 = [layout.block_size(b) for b in layout.build_blocks(["가나다."], [[[0]]])]
assert "left top" in il.layout_prompt(sizes1, ["left top"]) and "left top" not in il.layout_prompt(sizes1)
# 두 덩어리면 첫 그리기부터 1 은 왼쪽 면, 2 는 오른쪽 면에 빈 곳 (#95). 한 덩어리는 면을 정하지 않는다
sizes2 = [layout.block_size(b) for b in layout.build_blocks(["가나다.", "라마바."], [[[0]], [[1]]])]
assert "first one within the left half" in il.layout_prompt(sizes2) and "second one within the right half" in il.layout_prompt(sizes2)
assert "first one within the left half" not in il.layout_prompt(sizes1)
print("redraw cap / default spot ok:", dict(page_calls))

# 8-7) 두 덩어리는 양쪽에 자리가 없고 합친 한 덩어리는 있으면 합친 걸로 간다 — 다시 그리지 않는다 (settle을 그렇게 흉내 낸다)
one_page = st8.model_copy(update={"pages": st8.pages[:1]})
redraw_prompts: list[str] = []


def count_redraws(prompt, refs):
    if refs and "Scene" in prompt:
        page_calls.update(["x"])
        redraw_prompts.append(prompt)
    return mock.tiny_png(prompt, refs)


def only_merged_fits(busy, blocks, spots, avoid=()):
    return None if len(blocks) > 1 else layout.settle(busy, blocks, spots, avoid)


page_calls.clear()
places.clear()
il.set_image_override(count_redraws)
with patch.object(il, "settle", only_merged_fits):
    m = il.illustrate({"story": one_page, "output_prefix": "stories/t/runs/3/"})["illustrations"].pages[0]
assert places == [2, 1] and page_calls["x"] == 1, (places, page_calls)           # 합쳐서 찾았고 다시 그리지 않았다
assert len(m.text_blocks) == 1 and len(m.text_blocks[0].paragraphs) == 2          # 문단은 그대로
# 8-7-1) 나눠도 합쳐도 자리가 없으면 왼쪽 위·오른쪽 위로 다시 그려 나눠서·합쳐서 다시 찾고, 그래도 없으면 덜 복잡한 쪽 (#95)
page_calls.clear()
places.clear()
redraw_prompts.clear()
# 단색 가짜 그림은 calmest가 조용해 #113 문턱에서 다시 그리지 않는다 → 이 시험에서만 문턱(REDRAW_BUSY)을 끈다
with patch.object(il, "settle", lambda busy, blocks, spots, avoid=(): None), patch.object(il, "REDRAW_BUSY", -1.0):
    m2 = il.illustrate({"story": one_page, "output_prefix": "stories/t/runs/5/"})["illustrations"].pages[0]
assert places == [2, 1, 2, 1] and page_calls["x"] == 2, (places, page_calls)
assert "left top" in redraw_prompts[1] and "right top" in redraw_prompts[1], redraw_prompts[1][-400:]
assert len(m2.text_blocks) == 2 and m2.text_blocks[0].x < 50 <= m2.text_blocks[1].x, m2.text_blocks   # 단색 그림이라 같음 → 나눈다
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
secret = "비밀문장이에요. " * 6
long_page = one_line.model_copy(update={"pages": [one_line.pages[0].model_copy(update={"text": secret})]})
il.set_image_override(lambda p, refs: WEBP if refs and "Scene" in p else mock.tiny_png(p, refs))   # PIL이 못 읽는 그림
with captured_logs() as logged:
    m = il.illustrate({"story": long_page, "output_prefix": "stories/t/runs/5/"})["illustrations"].pages[0]
assert any("1" in x and "6" in x and "5줄 초과" in x for x in logged), logged
assert not any("비밀문장" in x for x in logged), logged
assert m.status == "completed" and len(m.text_blocks) == 1 and (m.text_blocks[0].x, m.text_blocks[0].y) == (5.0, 7.0), m
assert lines_of(m) == joined(secret)
il.set_image_override(mock.tiny_png)

# 8-10) 글 자리 계산이 터져도 쪽 그림과 생성은 이어 간다 (F1): 덩어리 나누기가 터지면 한 덩어리, 줄 나누기까지 터지면 빈 덩어리
good = il.illustrate({"story": st5, "output_prefix": "stories/t/runs/6/"})["illustrations"]
assert all(p.status == "completed" and p.text_blocks for p in good.pages)
edited = st5.model_copy(update={"pages": [st5.pages[0].model_copy(update={"text": "바뀐 글이에요. 둘째 줄이에요."})] + st5.pages[1:]})
with patch.object(il, "chunk_page", boom):
    broken = il.illustrate({"story": st5, "output_prefix": "stories/t/runs/7/"})["illustrations"]
    for pg, pi in zip(st5.pages, broken.pages):
        assert pi.status == "completed" and pi.path and pi.text_blocks and len(pi.text_blocks) == 1, pi   # 한 덩어리
        assert lines_of(pi) == joined(pg.text) and 0 <= pi.text_blocks[0].x <= 100, pi
    # 글만 바뀐 쪽 다시 자리 잡기(relayout)도 터져도 전체가 끝난다
    re1 = il.illustrate({"story": edited, "output_prefix": "stories/t/runs/8/", "illustrations": good, "redraw_pages": set()})["illustrations"]
    assert all(p.status == "completed" for p in re1.pages) and re1.pages[0].path == good.pages[0].path
    assert lines_of(re1.pages[0]) == joined("바뀐 글이에요. 둘째 줄이에요."), re1.pages[0]
    with patch.object(il, "split_lines", boom):   # 줄 나누기까지 터지면 빈 덩어리 — 그림은 그대로 완성
        empty = il.illustrate({"story": st5, "output_prefix": "stories/t/runs/9/"})["illustrations"]
        assert all(p.status == "completed" and p.path and p.text_blocks == [] for p in empty.pages), empty.pages
# relayout 자체가 터지면 그 쪽은 이전 그대로 두고 끝낸다
with patch.object(il, "_arrange", boom):
    kept = il.illustrate({"story": edited, "output_prefix": "stories/t/runs/10/", "illustrations": good, "redraw_pages": set()})["illustrations"]
    assert kept.pages[0] == good.pages[0] and all(p.status == "completed" for p in kept.pages)
print("layout failure keeps generating ok")

# 8-11) 그림만 다시 그릴 때는 덩어리 나누기를 다시 하지 않는다 (F2): layout:chunk 호출 0번, 덩어리는 이전 그대로
chunk_calls: list[str] = []
orig_chunk_page = il.chunk_page


def counting_chunk(text):
    chunk_calls.append(text)
    return orig_chunk_page(text)


with patch.object(il, "chunk_page", counting_chunk):
    again = il.illustrate({"story": st5, "output_prefix": "stories/t/runs/11/", "illustrations": good, "redraw_pages": {2, 3}})
assert not chunk_calls and not any(n.startswith("layout:chunk") for n in node_names(again["cost"])), (chunk_calls, node_names(again["cost"]))
a2, g2 = by_order(again["illustrations"].pages), by_order(good.pages)
for o in (2, 3):
    assert a2[o].path != g2[o].path and a2[o].status == "completed"
    assert [b.paragraphs for b in a2[o].text_blocks] == [b.paragraphs for b in g2[o].text_blocks]   # 덩어리 그대로
assert any(n.startswith("layout:place:page2") for n in node_names(again["cost"]))   # 자리는 새 그림에서 다시 찾는다
# 실패했던 쪽을 다시 그릴 때는 덩어리를 새로 나눈다
bad = good.model_copy(update={"pages": [good.pages[0].model_copy(update={"status": "failed", "path": None, "text_blocks": None})] + good.pages[1:]})
chunk_calls.clear()
with patch.object(il, "chunk_page", counting_chunk):
    il.illustrate({"story": st5, "output_prefix": "stories/t/runs/12/", "illustrations": bad, "redraw_pages": set()})
assert len(chunk_calls) == 1, chunk_calls
print("images regen skips chunking ok")

# 8-12) 강조(**)가 줄바꿈에서 닫혔다 다시 열려도 글이 그대로면 stale이 아니다 (F3). 진짜 글이 바뀌면 stale
emph_text = "**" + " ".join(["쿵쿵쿵쿵"] * 30) + "** 소리가 났어요."
emph_story = one_line.model_copy(update={"pages": [one_line.pages[0].model_copy(update={"text": emph_text})]})
em = il.illustrate({"story": emph_story, "output_prefix": "stories/t/runs/13/"})["illustrations"].pages[0]
assert "****" in raw_lines(em), em.text_blocks   # 줄바꿈에서 강조가 닫혔다 열림
assert not il._stale(emph_story.pages[0], em)
assert il._stale(emph_story.pages[0].model_copy(update={"text": emph_text + " 쿵"}), em)
print("emphasis wrap not stale ok")

# 8-13) 의성어 자리 (#92): 별표 말이 있는 쪽만 의성어 스키마로 묻고 sound_word를 싣는다
place_schemas: list[tuple[type, bool]] = []


def rec_place(**kw):
    if kw["node"] == "layout:place":
        place_schemas.append((kw["schema"], "깡충" in kw["system"]))
    return mock.fake_structured(**kw)


llm.set_structured_override(rec_place)
sfx_story = st5.model_copy(update={"pages": [pg.model_copy(update={"text": pg.text + "\n포포가 **깡충** 뛰었어요."}) if pg.order % 2 else pg
                                             for pg in st5.pages]})
sw_ill = il.illustrate({"story": sfx_story, "output_prefix": "stories/t/runs/20/"})["illustrations"]
for pi in sw_ill.pages:
    if pi.order % 2:
        assert pi.sound_word and pi.sound_word.text == "깡충" and pi.sound_word.color.startswith("#") and len(pi.sound_word.color) == 7, pi
        assert 1 <= len(pi.sound_word.pieces) <= 2 and all(0 <= q.x <= 100 and 0 <= q.y <= 100 for q in pi.sound_word.pieces), pi
    else:
        assert pi.sound_word is None, pi
assert sorted((sc.__name__, k) for sc, k in place_schemas) == sorted(
    [("TextPlacementWithWord", True)] * 3 + [("TextPlacement", False)] * 2), place_schemas

# 아무것도 다시 하지 않은 쪽은 이전 sound_word 그대로 (그림만 다시 2쪽)
kept_sw = il.illustrate({"story": sfx_story, "output_prefix": "stories/t/runs/21/", "illustrations": sw_ill, "redraw_pages": {2}})["illustrations"]
assert {p.order: p.sound_word for p in kept_sw.pages if p.order != 2} == {p.order: p.sound_word for p in sw_ill.pages if p.order != 2}

# 글만 바뀌어 그림은 그대로인 쪽(relayout)도 새 글의 별표 말로 자리를 다시 찾는다
thud = sfx_story.model_copy(update={"pages": [pg.model_copy(update={"text": "2쪽 첫 줄이에요.\n**쿵** 소리가 났어요."}) if pg.order == 2 else pg
                                          for pg in sfx_story.pages]})
re_sw = il.illustrate({"story": thud, "output_prefix": "stories/t/runs/22/", "illustrations": sw_ill, "redraw_pages": set()})["illustrations"]
p2_old, p2_new = page_of(sw_ill.pages, 2), page_of(re_sw.pages, 2)
assert p2_new.path == p2_old.path and p2_new.sound_word and p2_new.sound_word.text == "쿵", p2_new

# 별표 말이 둘이면 첫 번째만, 로그에는 쪽 번호와 개수만
two_words = sfx_story.model_copy(update={"pages": [sfx_story.pages[0].model_copy(update={"text": "**톡** 하고 **쿵** 했어요."})]})
with captured_logs() as logged:
    tw = il.illustrate({"story": two_words, "output_prefix": "stories/t/runs/23/"})["illustrations"].pages[0]
assert tw.sound_word.text == "톡", tw
assert any("의성어 2개" in x for x in logged) and not any("톡" in x or "쿵" in x for x in logged), logged


def word_at(x0: int, y0: int) -> TextPlacementWithWord:
    """덩어리는 (5, 7), 포포 얼굴 칸은 (x0, y0)에서 가로 6·세로 10(%)인 자리 답"""
    return TextPlacementWithWord(blocks=[mock.BlockSpot(x=5, y=7, color="dark")],
                                 sound_word=mock.WordSpot(owner="포포", source_kind="face",
                                                          source_box=mock.OwnerBox(x0=x0, y0=y0, x1=x0 + 6, y1=y0 + 10)))


def placements_then_fail(*answers):
    """layout:place 호출마다 answers를 차례로 답하고, 다 쓰면 터진다."""
    remaining = iter(answers)

    def fn(**kw):
        if kw["node"] != "layout:place":
            return mock.fake_structured(**kw)
        answer = next(remaining, None)
        if answer is None:
            raise RuntimeError("boom")
        return answer
    return fn


# 글 자리 때문에 다시 그렸는데 새 그림으로 답을 못 받으면 처음 그림의 말 자리를 쓰지 않는다 (None)
ask = layout.SfxAsk(word="깡충", text="포포가 **깡충** 뛰었어요.", cast=[("포포", "rabbit")])
llm.set_structured_override(placements_then_fail(word_at(70, 30)))
_, sw = il._arrange(1, striped_png(), [[["포포가 깡충 뛰었어요."]]], [], lambda bl, where: striped_png(), ask)
assert sw is None, sw
# 다시 그린 그림으로 답을 받으면 그 답의 자리를 쓴다
llm.set_structured_override(placements_then_fail(word_at(70, 30), word_at(20, 50)))
_, sw = il._arrange(1, striped_png(), [[["포포가 깡충 뛰었어요."]]], [], lambda bl, where: striped_png((0, 0, 100, 100)), ask)
assert sw is not None and len(sw.pieces) == 1 and sw.pieces[0].x < 50 and sw.pieces[0].y < 50, sw   # 두 번째(다시 그린 그림) 답의 근원 위
# AI가 캐릭터 칸을 하나도 안 주면 쪽 번호만 경고 (실험에서 null·겹침 원인을 알아보려고)
llm.set_structured_override(placements_then_fail(word_at(70, 30)))
with captured_logs() as logged:
    il._arrange(3, striped_png(), [[["포포가 깡충 뛰었어요."]]], [], None, ask)
assert any("쪽 3" in x and "캐릭터 칸 없음" in x for x in logged) and not any("포포" in x for x in logged), logged
# 의성어 준비가 터져도 그 쪽 그림은 완성, 의성어만 None (리뷰 #3)
llm.set_structured_override(mock.fake_structured)
with patch.object(il, "short_look", boom):
    sb = il.illustrate({"story": sfx_story, "output_prefix": "stories/t/runs/24/"})["illustrations"]
assert all(p.status == "completed" and p.text_blocks and p.sound_word is None for p in sb.pages), sb.pages


# 별표 말이 있는데 의성어를 못 놓으면 쪽 번호만 경고 (리뷰 #4)
def no_word_spot(**kw):
    if kw["node"] == "layout:place":
        return TextPlacementWithWord.model_construct(blocks=[mock.BlockSpot(x=5, y=7, color="dark")], sound_word=None)
    return mock.fake_structured(**kw)


llm.set_structured_override(no_word_spot)
with captured_logs() as logged:
    nw = il.illustrate({"story": two_words, "output_prefix": "stories/t/runs/25/"})["illustrations"].pages[0]
assert nw.sound_word is None and any("쪽 1" in x and "의성어 자리 없음" in x for x in logged), logged
assert not any("톡" in x for x in logged), logged
llm.set_structured_override(recording_structured)
print("sound word ok")

# 8-14) 글은 캐릭터 칸을 피하고, 자리가 없으면 한 덩어리를 양쪽으로 나눈다 (#104)
white_png = striped_png((0, 0, 100, 100))
b7 = [[[f"미루가 블록을 {i}번 쌓았어요." for i in range(1, 8)]]]   # 덩어리 1개 = 문단 1개 7줄


def chars_seq(*seq):
    """자리 찾기 호출마다 seq의 캐릭터 칸(%)을 차례로 답한다(마지막 것을 되풀이). 덩어리 자리는 늘 (5, 7)"""
    remaining, current = iter(seq), seq[-1]

    def fn(**kw):
        nonlocal current
        if kw["node"] != "layout:place":
            return mock.fake_structured(**kw)
        current = next(remaining, current)
        n = len(re.findall(r"^\d+번 덩어리", kw["system"], re.M))
        return TextPlacement(blocks=[mock.BlockSpot(x=5, y=7, color="dark")] * n,
                             characters=[mock.CharacterBox(name=f"c{i}", box=mock.OwnerBox(x0=a, y0=b, x1=c, y1=d))
                                         for i, (a, b, c, d) in enumerate(current)])
    return fn


redraws: list = []


def redraw_to(img):
    def f(bl, where):
        redraws.append(where)
        return img
    return f


def over(tbs, chars):
    av = layout.blockers([("c", c) for c in chars])
    return sum(layout._overlap(t.x / 100 * layout.W, t.y / 100 * layout.H, *layout.block_size(t.paragraphs), av) for t in tbs)


# 7줄 한 덩어리는 어느 위 띠에서도 칸에 닿는다 → 나눠서 양쪽 면, 다시 그리기 없이
split_chars = [(0, 45, 50, 100), (50, 50, 100, 100)]
llm.set_structured_override(chars_seq(split_chars))
redraws.clear()
tbs, _ = il._arrange(1, white_png, b7, [], redraw_to(white_png))
assert len(tbs) == 2 and tbs[0].x < 50 <= tbs[1].x and over(tbs, split_chars) == 0 and redraws == [], tbs
assert [l for t in tbs for para in t.paragraphs for l in para] == [l for para in b7[0] for l in para]
# 나눠도 안 들어가면 다시 그리기
llm.set_structured_override(chars_seq([(0, 15, 100, 100)]))
redraws.clear()
tbs, _ = il._arrange(1, white_png, b7, [], redraw_to(white_png))
assert len(redraws) == 1 and tbs, tbs
# Review Focus 1: 그림 전체가 칸이어도 늘 유효한 자리
llm.set_structured_override(chars_seq([(0, 0, 100, 100)]))
tbs, _ = il._arrange(1, white_png, b7, [], redraw_to(white_png))
assert tbs and all(0 <= t.x <= 100 and 0 <= t.y <= 100 for t in tbs), tbs
# Review Focus 2: 다시 그린 그림에는 그 그림 답의 칸만 쓴다 (처음 그림의 칸이 남지 않는다)
llm.set_structured_override(chars_seq([(0, 0, 100, 100)], []))
redraws.clear()
tbs, _ = il._arrange(1, white_png, [[["포포가 깡충 뛰었어요."]]], [], redraw_to(white_png))
assert len(redraws) == 1 and (tbs[0].x, tbs[0].y) == (5.0, 7.0), tbs
# Review Focus 5: 칸이 없으면 지금처럼 AI 자리 그대로
llm.set_structured_override(chars_seq([]))
redraws.clear()
tbs, _ = il._arrange(1, white_png, b7, [], redraw_to(white_png))
assert len(tbs) == 1 and (tbs[0].x, tbs[0].y) == (5.0, 7.0) and redraws == [], tbs
# 칸이 없어도 한 덩어리가 들어갈 곳이 없으면 나눠서 양쪽 면 — 다시 그리기를 아낀다 (리뷰 판단: 설계 4번은 칸 여부와 상관없음)
llm.set_structured_override(chars_seq([]))
redraws.clear()
tbs, _ = il._arrange(1, striped_png((0, 0, 100, 40)), b7, [], redraw_to(white_png))
assert len(tbs) == 2 and tbs[0].x < 50 <= tbs[1].x and redraws == [], tbs

# #113: 자리 기준(BUSY_LIMIT)은 넘지만 문턱(REDRAW_BUSY) 이하이고 몸 겹침이 없으면 다시 그리지 않는다
faint = faint_png(30)
assert layout.BUSY_LIMIT < layout._score(layout.Busy(faint), 100, 80, *layout.block_size(b7[0])) <= layout.REDRAW_BUSY
llm.set_structured_override(chars_seq([]))
redraws.clear()
tbs, _ = il._arrange(1, faint, b7, [], redraw_to(white_png))
assert redraws == [] and tbs, (redraws, tbs)
# 문턱을 넘으면 지금처럼 다시 그린다
loud = faint_png(60)
assert layout._score(layout.Busy(loud), 100, 80, *layout.block_size(b7[0])) > layout.REDRAW_BUSY
redraws.clear()
tbs, _ = il._arrange(1, loud, b7, [], redraw_to(white_png))
assert len(redraws) == 1, redraws
llm.set_structured_override(recording_structured)
print("avoid characters ok")


# 8-x) 가이드 질문은 그 쪽 마지막 덩어리의 맨 밑 새 문단 (#100). 원고·덩어리 나누기 AI에는 질문이 없다
def guide_of(*pairs):   # (after_page, text)
    return ReadingGuide(synopsis="s", prompts=[GuidePrompt(id=f"q{i}", after_page=a, text=t, purpose="empathy")
                                               for i, (a, t) in enumerate(pairs)],
                        before_reading=BeforeReading(intent="i", tips=["t"]), after_reading=AfterReading(bridge_question="b"))


Q = "포포가 울었어요. 포포 마음은 어땠을까요?"
qs = il._questions(guide_of((2, Q), (2, "다음엔 어떻게 할까요?"), (0, "범위 밖?"), (99, "범위 밖?")))
assert qs[2] == ["포포가 울었어요.", "포포 마음은 어땠을까요?", "다음엔 어떻게 할까요?"], qs
assert il._questions(None) == {}
st_q = st5.model_copy(update={"pages": [pg.model_copy(update={"text": f"{pg.order}쪽 첫 줄이에요. 둘째 줄이에요. 셋째 줄이에요."})
                                        for pg in st5.pages[:3]]})
il.set_image_override(mock.tiny_png)
chunk_sys: list[str] = []


def chunk_rec(**kw):
    if kw["schema"] is TextChunking:
        chunk_sys.append(kw["system"])
    return mock.fake_structured(**kw)


llm.set_structured_override(chunk_rec)
gq = guide_of((2, Q), (2, "다음엔 어떻게 할까요?"), (99, "범위 밖?"))
ill_q = il.illustrate({"story": st_q, "guide": gq, "output_prefix": "stories/q/runs/1/"})["illustrations"]
p2 = page_of(ill_q.pages, 2)
assert last_para(p2) == qs[2], p2.text_blocks                                           # 마지막 덩어리의 마지막 문단 = 질문 줄
assert len(p2.text_blocks[-1].paragraphs) >= 2, p2.text_blocks                          # 본문과 다른 문단
assert lines_of(p2) == joined(st_q.pages[1].text + "".join(qs[2])), lines_of(p2)         # 본문 다음 질문
assert not any("마음은" in s or "다음엔" in s for s in chunk_sys), chunk_sys              # 덩어리 나누기 AI에 질문을 안 넘김
assert all(lines_of(pi) == joined(pg.text) for pg, pi in zip(st_q.pages, ill_q.pages) if pi.order != 2)   # 다른 쪽엔 없음
assert st_q.pages[1].text.endswith("셋째 줄이에요.")                                      # 원고 그대로
assert not il._stale(st_q.pages[1], p2, qs[2]) and il._stale(st_q.pages[1], p2, [])       # 질문까지 같아야 그대로
ill_none = il.illustrate({"story": st_q, "output_prefix": "stories/q/runs/2/"})["illustrations"]
assert [pi.text_blocks for pi in ill_none.pages if pi.order != 2] == [pi.text_blocks for pi in ill_q.pages if pi.order != 2]
assert lines_of(ill_none.pages[1]) == joined(st_q.pages[1].text)                         # 가이드가 없으면 지금과 같다
# 두 덩어리로 나뉘어도 질문은 둘째 덩어리 끝 (합쳐지면 한 덩어리의 끝)
llm.set_structured_override(lambda **kw: TextChunking(blocks=[[[0]], [[1, 2]]]) if kw["schema"] is TextChunking
                            else mock.fake_structured(**kw))
ill_q2 = il.illustrate({"story": st_q, "guide": gq, "output_prefix": "stories/q/runs/3/"})["illustrations"]
p2b = ill_q2.pages[1]
assert last_para(p2b) == qs[2] and lines_of(p2b) == lines_of(p2), p2b.text_blocks
# 그림만 다시(illustrate_only)도 같은 질문을 붙인다. 글·질문이 그대로인 쪽은 덩어리를 다시 나누지 않는다
llm.set_structured_override(chunk_rec)
chunk_sys.clear()
again = il.illustrate_only({"story": st_q, "guide": gq, "illustrations": ill_q, "regenerate_pages": [2],
                            "output_prefix": "stories/q/runs/4/"})["illustrations"]
assert last_para(again.pages[1]) == qs[2] and not chunk_sys, (again.pages[1].text_blocks, chunk_sys)
# 리뷰 #2: 다시 만들 때 질문이 새로 붙은 쪽은 그 그림에 질문 자리가 없을 수 있다 → 자리를 못 찾으면 다시 그리기 허용 (실행당 상한 그대로)
llm.set_structured_override(mock.fake_structured)
il.set_image_override(lambda p, refs: striped_png() if refs and "Scene" in p else mock.tiny_png(p, refs))
busy_prev = il.illustrate({"story": st_q, "output_prefix": "stories/q/runs/5/"})["illustrations"]   # 질문 없이 그린 그림
moved_q = il.illustrate({"story": st_q, "guide": gq, "illustrations": busy_prev, "redraw_pages": [],
                         "output_prefix": "stories/q/runs/6/"})
mq = by_order(moved_q["illustrations"].pages)
assert mq[2].path.startswith("stories/q/runs/6/"), mq[2].path                                 # 질문이 새로 붙은 2쪽은 다시 그림
assert last_para(mq[2]) == qs[2], mq[2].text_blocks
mq_nodes = node_names(moved_q["cost"])
assert "illustrate:page2" in mq_nodes and not any(n in mq_nodes for n in ("illustrate:page1", "illustrate:page3")), mq_nodes
assert mq[1].path == busy_prev.pages[0].path and mq[3].path == busy_prev.pages[2].path        # 나머지 쪽은 그대로
# 질문이 그대로인 쪽은 글만 바뀌어도 다시 그리지 않는다 (지금처럼 자리만)
body_only = st_q.model_copy(update={"pages": [pg.model_copy(update={"text": pg.text + " 넷째 줄이에요."}) if pg.order == 2 else pg
                                              for pg in st_q.pages]})
same_q = il.illustrate({"story": body_only, "guide": gq, "illustrations": moved_q["illustrations"], "redraw_pages": [],
                        "output_prefix": "stories/q/runs/7/"})
assert same_q["illustrations"].pages[1].path == mq[2].path and not any(n.startswith("illustrate:page") for n in node_names(same_q["cost"])), same_q["cost"]
il.set_image_override(mock.tiny_png)
llm.set_structured_override(recording_structured)
print("question in page ok")

print("text blocks ok")

print("\nALL OK")
