"""
다중 음성 낭독(TTS) 배선 확인. API 없이 돈다. (uv run python evals/narrate_check.py)
ElevenLabs는 절대 실제로 부르지 않는다: tts.set_tts_override 또는 tts.config 패치만 쓴다.
"""
from __future__ import annotations

import http.client
import io
import json
import logging
import sys
import tempfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstory import llm, mock, storage, tts, voices  # noqa: E402
from firstory.schemas import (  # noqa: E402
    CastVoice, CharacterSheet, CostEntry, Narration, PageAudio, QuoteSpeaker, SpeakerAssignment, StoryPage, StoryText,
)


def story_with(pages: dict[int, str], cast: list[str]) -> StoryText:
    """쪽 번호 → 글, 이름들(첫 이름이 주인공, 나머지 조연). 1쪽부터 마지막 쪽까지 빠진 쪽은 해설 글 '…'."""
    chars = [CharacterSheet(name=n, role="protagonist" if i == 0 else "supporting", visual_description=f"a friendly {n}")
             for i, n in enumerate(cast)]
    ps = [StoryPage(order=o, text=pages.get(o, "…"), characters_in_scene=list(cast), image_prompt="a scene")
          for o in range(1, max(pages) + 1)]
    return StoryText(title="t", characters=chars, style_guide="watercolor", pages=ps)


def boom(**kw):
    raise AssertionError("모델을 부르면 안 된다")


# --- Task 1: 스키마·설정·클라이언트 ---
assert CostEntry(node="x", model="y").tts_chars == 0
assert voices.NARRATOR not in {v for vs in voices.POOL.values() for v in vs}
assert len({v for vs in voices.POOL.values() for v in vs}) == sum(len(vs) for vs in voices.POOL.values())  # 겹침 없음
seen = []
tts.set_tts_override(lambda inputs: seen.append(inputs) or b"ID3fake")
assert tts.enabled() and tts.dialogue([{"text": "안녕", "voice_id": voices.NARRATOR}], page=1) == b"ID3fake"
tts.set_tts_override(None)
with patch.object(tts, "config", SimpleNamespace(elevenlabs_api_key="")):
    assert not tts.enabled()   # 키도 override도 없으면 꺼짐
assert Narration().pages == [] and PageAudio(order=1, status="failed").path is None

# --- Task 2: 조각 나누기와 목소리 배정 ---
from firstory.nodes import narrate as nr  # noqa: E402

s = nr.segments(2, '곰 하늬가 왔어요.\n"라니야, 옷 입자." 하고 말했어요.\n"싫어!"')
assert [(x.text, x.quoted, x.id) for x in s] == [
    ("곰 하늬가 왔어요.", False, None), ("라니야, 옷 입자.", True, "2-1"),
    ("하고 말했어요.", False, None), ("싫어!", True, "2-2")]
assert [x.text for x in nr.segments(1, "라니는 **쏙** 들어갔어요.")] == ["라니는 쏙 들어갔어요."]
assert [(x.text, x.quoted) for x in nr.segments(1, "“안녕!” 소리가 났어요.")] == [("안녕!", True), ("소리가 났어요.", False)]
assert "".join(x.text for x in nr.segments(1, '라니가 "같이 놀자 말했어요.')).replace(" ", "") == "라니가같이놀자말했어요."  # 짝 없는 따옴표: 글이 빠지지 않는다
assert nr.segments(1, '""') == []

v = nr.cast_voices({"라니": "child_girl", "보리": "child_girl", "하늬": "adult_man"})
assert len(set(v.values())) == 3 and voices.NARRATOR not in v.values()
assert v["라니"] == voices.POOL["child_girl"][0] and v["보리"] == voices.POOL["child_girl"][1]
assert nr.cast_voices({"라니": "adult_man"}, keep={"라니": "keep-id"}) == {"라니": "keep-id"}
three = nr.cast_voices({"a": "elder_man", "b": "elder_man", "c": "elder_man"})
assert len(set(three.values())) == 3   # 풀이 모자라면 다른 풀에서

# 노드: 모델이 엉뚱한 이름·없는 id·빠진 id를 줘도 narrator
llm.set_structured_override(lambda **kw: SpeakerAssignment(
    cast=[CastVoice(name="라니", voice_type="child_girl"), CastVoice(name="유령", voice_type="adult_man")],
    quotes=[QuoteSpeaker(id="2-1", speaker="하늬"), QuoteSpeaker(id="2-2", speaker="모르는애"), QuoteSpeaker(id="9-9", speaker="라니")]))
out = nr.assign_voices({"story": story_with(pages={2: '"라니야, 옷 입자."\n"싫어!"\n"응."'}, cast=["라니", "하늬"])})
assert out["voice_plan"]["speakers"] == {"2-1": "하늬", "2-2": "narrator", "2-3": "narrator"}
assert set(out["voice_plan"]["cast_types"]) == {"라니", "하늬"} and out["voice_plan"]["cast_types"]["하늬"] == "adult_woman"
# 대사 없는 동화는 모델을 부르지 않는다
llm.set_structured_override(boom)
assert nr.assign_voices({"story": story_with(pages={1: "라니는 잤어요."}, cast=["라니"])})["cost"] == []
# 글 다시 만들기: 이전 배정 유지, 새 인물만 새로
prev = Narration(cast_types={"하늬": "adult_man"}, cast_voices={"하늬": "keep-id"})
llm.set_structured_override(lambda **kw: SpeakerAssignment(
    cast=[CastVoice(name="하늬", voice_type="child_boy"), CastVoice(name="라니", voice_type="child_girl")],
    quotes=[QuoteSpeaker(id="1-1", speaker="하늬")]))
out = nr.assign_voices({"story": story_with(pages={1: '"자자."'}, cast=["라니", "하늬"]),
                        "narration": prev, "regenerate_scope": "text"})
assert out["voice_plan"]["cast_voices"]["하늬"] == "keep-id" and out["voice_plan"]["cast_types"]["하늬"] == "adult_man"
llm.set_structured_override(None)

# --- Task 3: 쪽마다 음성 만들기 ---
class _Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextmanager
def captured_logs():
    """firstory.narrate 로그 메시지를 모은다."""
    handler = _Grab()
    logger = logging.getLogger("firstory.narrate")
    logger.addHandler(handler)
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)


tmp = tempfile.mkdtemp()
base = "stories/narr"
storage_patch = patch.object(storage, "config", SimpleNamespace(storage="local", output_root=Path(tmp)))
storage_patch.start()   # 파일은 임시 폴더에만 쓴다

plan = {"cast_types": {"라니": "child_girl"}, "cast_voices": {"라니": "v-rani"}, "speakers": {"2-1": "라니", "2-2": "라니"}}
assert nr.page_inputs(2, '라니는 왔어요.\n"싫어!"\n"안 입어."\n라니는 숨었어요.', plan) == [
    {"text": "라니는 왔어요.", "voice_id": voices.NARRATOR}, {"text": "싫어! 안 입어.", "voice_id": "v-rani"},
    {"text": "라니는 숨었어요.", "voice_id": voices.NARRATOR}]
assert nr.page_inputs(1, "라니는 잤어요.", {"cast_types": {}, "cast_voices": {}, "speakers": {}}) == [
    {"text": "라니는 잤어요.", "voice_id": voices.NARRATOR}]   # 대사 없는 쪽 = 해설 하나
# 목소리 표에 없는 말한 사람은 해설자 목소리
assert nr.page_inputs(2, '"싫어!"', {"cast_voices": {}, "speakers": {"2-1": "유령"}}) == [{"text": "싫어!", "voice_id": voices.NARRATOR}]
assert nr.source_hash([{"text": "가", "voice_id": "a"}]) == nr.source_hash([{"voice_id": "a", "text": "가"}])
assert nr.source_hash([{"text": "가", "voice_id": "a"}]) != nr.source_hash([{"text": "가", "voice_id": "b"}])

calls = []
def fake_tts(inputs):
    calls.append(inputs)
    if inputs[0]["text"].startswith("3쪽"):
        raise tts.TtsError("quota_exceeded", status=402)
    return b"ID3" + inputs[0]["text"].encode()
tts.set_tts_override(fake_tts)
st = {"story": story_with(pages={i: f"{i}쪽 글이에요." for i in range(1, 4)}, cast=["라니"]),
      "voice_plan": {"cast_types": {}, "cast_voices": {}, "speakers": {}}, "output_prefix": f"{base}/1/"}
with captured_logs() as logs:
    out = nr.narrate(st)
n1 = out["narration"]
assert [(p.order, p.status) for p in n1.pages] == [(1, "completed"), (2, "completed"), (3, "failed")]
assert n1.pages[0].path == f"{base}/1/audio/page-01.mp3" and storage.read_bytes(n1.pages[0].path).startswith(b"ID3")
assert "402" in n1.pages[2].error and any("3쪽 음성 실패" in m and "402" in m for m in logs)
assert len(calls) == 4   # 3쪽은 한 번 더 시도
assert sorted((c.node, c.tts_chars) for c in out["cost"]) == [("narrate:page1", len("1쪽 글이에요.")),
                                                              ("narrate:page2", len("2쪽 글이에요."))]

# 다시 만들기: 2쪽 글만 바뀜 → 2·3쪽만 다시(3쪽은 이전에 실패), 1쪽은 이전 key
calls.clear(); tts.set_tts_override(lambda i: calls.append(i) or b"ID3x")
st2 = {**st, "story": story_with(pages={1: "1쪽 글이에요.", 2: "2쪽 바뀐 글.", 3: "3쪽 글이에요."}, cast=["라니"]),
       "narration": n1, "output_prefix": f"{base}/2/"}
n2 = nr.narrate(st2)["narration"]
assert n2.pages[0].path == f"{base}/1/audio/page-01.mp3" and n2.pages[1].path == f"{base}/2/audio/page-02.mp3"
assert len(calls) == 2

# 키도 override도 없으면 아무것도 안 부른다
tts.set_tts_override(None)
with patch.object(tts, "config", SimpleNamespace(elevenlabs_api_key="")):
    assert nr.narrate(st) == {"narration": None, "cost": []}

# mock: 조용한 mp3
assert mock.silent_mp3([{"text": "가", "voice_id": "a"}]).startswith(b"ID3")

# tts HTTP 매핑 (urlopen을 바꿔 치운다, 네트워크 없음)
class _Resp:
    def __init__(self, body=b"", exc=None):
        self.body, self.exc = body, exc
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self):
        if self.exc:
            raise self.exc
        return self.body

def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"detail"))

def run_dialogue(steps):
    """steps: 호출 순서대로 돌려줄 응답 또는 던질 예외. → (결과 또는 TtsError, 본문 목록)"""
    bodies, it = [], iter(steps)
    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data))
        step = next(it)
        if isinstance(step, Exception):
            raise step
        return step
    with patch.object(tts, "config", SimpleNamespace(elevenlabs_api_key="k", tts_model="m")), \
         patch.object(urllib.request, "urlopen", fake_urlopen):
        try:
            return tts.dialogue([{"text": "가", "voice_id": "a"}], page=1), bodies
        except tts.TtsError as e:
            return e, bodies

res, bodies = run_dialogue([http_error(400), _Resp(b"ID3ok")])
assert res == b"ID3ok" and "language_code" in bodies[0] and "language_code" not in bodies[1]
res, bodies = run_dialogue([http_error(500)])
assert isinstance(res, tts.TtsError) and res.status == 500 and len(bodies) == 1
res, _ = run_dialogue([urllib.error.URLError("down")])
assert isinstance(res, tts.TtsError) and res.status is None
res, _ = run_dialogue([_Resp(exc=http.client.IncompleteRead(b"x"))])
assert isinstance(res, tts.TtsError) and res.status is None
storage_patch.stop()

print("ALL OK")
