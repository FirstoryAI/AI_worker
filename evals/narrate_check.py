"""
다중 음성 낭독(TTS) 배선 확인. API 없이 돈다. (uv run python evals/narrate_check.py)
ElevenLabs는 절대 실제로 부르지 않는다: tts.set_tts_override 또는 tts.config 패치만 쓴다.
"""
from __future__ import annotations

import http.client
import io
import json
import logging
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import replace
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

def no_tts(inputs):
    raise AssertionError("음성을 부르면 안 된다")


tts.set_tts_override(no_tts)   # 낭독이 켜져 있어야 assign_voices가 모델을 부른다 (키 없이 돌려도)

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
retry_patch = patch.object(nr, "_retry_wait", lambda: None)
retry_patch.start()   # 다시 시도 전 기다림은 0초로

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
assert len(calls) == 3   # 402는 다시 해도 같아서 한 번만
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

def http_error(code, body=b"detail"):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(body))

def run_dialogue(steps):
    """steps: 호출 순서대로 돌려줄 응답 또는 던질 예외. → (결과 또는 TtsError, 본문 목록)"""
    bodies, it = [], iter(steps)
    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data))
        step = next(it)
        if isinstance(step, Exception):
            raise step
        return step
    with patch.object(tts, "config", SimpleNamespace(elevenlabs_api_key="k", tts_model="m", tts_timeout=60)), \
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
# 어떤 실패도 그 쪽만 failed (R3): 일반 예외, 저장 실패, 모델 실패
tts.set_tts_override(lambda i: (_ for _ in ()).throw(RuntimeError("뜻밖")) if i[0]["text"].startswith("2쪽") else b"ID3y")
with captured_logs() as logs:
    n3 = nr.narrate({**st, "output_prefix": f"{base}/3/"})["narration"]
assert [(p.order, p.status) for p in n3.pages] == [(1, "completed"), (2, "failed"), (3, "completed")]
assert "뜻밖" in n3.pages[1].error and any("2쪽 음성 실패" in m for m in logs)
tts.set_tts_override(lambda i: b"ID3z")
real_write = storage.write_bytes
def flaky_write(key, data):
    if key.endswith("page-02.mp3"):
        raise OSError("디스크 가득")
    return real_write(key, data)
with patch.object(storage, "write_bytes", flaky_write):
    out4 = nr.narrate({**st, "output_prefix": f"{base}/4/"})
assert [(p.order, p.status) for p in out4["narration"].pages] == [(1, "completed"), (2, "failed"), (3, "completed")]
assert [c.node for c in sorted(out4["cost"], key=lambda c: c.node)] == ["narrate:page1", "narrate:page3"]
tts.set_tts_override(None)

def raising(**kw):
    raise RuntimeError("모델 실패")
llm.set_structured_override(raising)
tts.set_tts_override(no_tts)
with captured_logs() as logs:
    fb = nr.assign_voices({"story": story_with(pages={1: '"안녕!"'}, cast=["라니", "하늬"])})
assert fb["voice_plan"]["speakers"] == {} and fb["cost"] == []
assert fb["voice_plan"]["cast_types"] == {"라니": "child_girl", "하늬": "adult_woman"} and set(fb["voice_plan"]["cast_voices"]) == {"라니", "하늬"}
assert any("말한 사람 정하기 실패" in m for m in logs)
llm.set_structured_override(None)

# --- 마지막 고치기 (R4): 글만 다시 만들 때 글이 바뀐 쪽 대사만 다시 정한다 ---
calls = []
tts.set_tts_override(lambda i: calls.append(i) or b"ID3r")
pages_v1 = {1: "라니가 일어났어요.", 2: '"안녕!" 라니가 말했어요.\n"반가워." 하늬가 말했어요.', 3: '"놀자!" 하늬가 말했어요.'}
story_v1 = story_with(pages=pages_v1, cast=["라니", "하늬"])
llm.set_structured_override(lambda **kw: SpeakerAssignment(
    cast=[CastVoice(name="라니", voice_type="child_girl"), CastVoice(name="하늬", voice_type="child_boy")],
    quotes=[QuoteSpeaker(id="2-1", speaker="라니"), QuoteSpeaker(id="2-2", speaker="하늬"), QuoteSpeaker(id="3-1", speaker="하늬")]))
plan_v1 = nr.assign_voices({"story": story_v1})["voice_plan"]
nar_v1 = nr.narrate({"story": story_v1, "voice_plan": plan_v1, "output_prefix": f"{base}/r1/"})["narration"]
assert nar_v1.speakers == {"2-1": "라니", "2-2": "하늬", "3-1": "하늬"} and len(calls) == 3
assert [p.text_hash for p in nar_v1.pages] == [nr.text_hash(pages_v1[o]) for o in (1, 2, 3)]
assert nar_v1.model_dump(mode="json")["speakers"] == nar_v1.speakers   # 06-narration.json에도 남는다

story_v2 = story_with(pages={**pages_v1, 3: '"같이 놀자!" 라니가 말했어요.'}, cast=["라니", "하늬"])
st_v2 = {"story": story_v2, "narration": nar_v1, "regenerate_scope": "text"}
sent: list[str] = []
def labeler(**kw):
    sent.extend(re.findall(r"\[(\d+-\d+)\] 줄:", kw["system"]))
    return SpeakerAssignment(cast=[], quotes=[QuoteSpeaker(id="3-1", speaker="라니"), QuoteSpeaker(id="2-1", speaker="하늬")])
llm.set_structured_override(labeler)
plan_v2 = nr.assign_voices(st_v2)["voice_plan"]
assert sent == ["3-1"]   # 글이 그대로인 2쪽 대사는 모델에게 보내지 않는다
assert plan_v2["speakers"] == {"2-1": "라니", "2-2": "하늬", "3-1": "라니"}   # 2쪽은 이전 그대로 (모델이 2-1을 줘도 무시)
assert plan_v2["cast_voices"] == plan_v1["cast_voices"]
calls.clear()
nar_v2 = nr.narrate({**st_v2, "voice_plan": plan_v2, "output_prefix": f"{base}/r2/"})["narration"]
assert len(calls) == 1 and calls[0][0] == {"text": "같이 놀자!", "voice_id": plan_v1["cast_voices"]["라니"]}
assert [p.path for p in nar_v2.pages] == [nar_v1.pages[0].path, nar_v1.pages[1].path, f"{base}/r2/audio/page-03.mp3"]
assert nar_v2.pages[2].text_hash == nr.text_hash(story_v2.pages[2].text) and nar_v2.speakers == plan_v2["speakers"]
# 글이 전부 그대로면 모델을 부르지 않는다
llm.set_structured_override(boom)
assert nr.assign_voices({**st_v2, "story": story_v1})["voice_plan"]["speakers"] == nar_v1.speakers
# 이야기 다시 만들기는 전부 다시 정한다
sent.clear(); llm.set_structured_override(labeler)
nr.assign_voices({**st_v2, "regenerate_scope": "story"})
assert sent == ["2-1", "2-2", "3-1"]
# 글만 다시 만들 때 모델이 실패: 2쪽은 이전 말한 사람 그대로(다시 녹음 안 함), 바뀐 3쪽만 해설자
llm.set_structured_override(raising)
with captured_logs() as logs:
    plan_v3 = nr.assign_voices(st_v2)["voice_plan"]
assert plan_v3["speakers"] == {"2-1": "라니", "2-2": "하늬"} and any("말한 사람 정하기 실패" in m for m in logs)
calls.clear()
nar_v3 = nr.narrate({**st_v2, "voice_plan": plan_v3, "output_prefix": f"{base}/r3/"})["narration"]
assert len(calls) == 1 and calls[0] == [{"text": "같이 놀자! 라니가 말했어요.", "voice_id": voices.NARRATOR}]
assert nar_v3.pages[1].path == nar_v1.pages[1].path
llm.set_structured_override(None)

# --- 마지막 고치기 (R5): 전체 시간, 차단기, 다시 시도 ---
three = story_with(pages={i: f"{i}쪽 글이에요." for i in range(1, 4)}, cast=["라니"])
st_t = {"story": three, "voice_plan": {"cast_types": {}, "cast_voices": {}, "speakers": {}}, "output_prefix": f"{base}/t/"}
one_at_a_time = replace(nr.config, tts_concurrency=1)
calls.clear()
with patch.object(nr, "config", replace(nr.config, tts_deadline=0)):
    out = nr.narrate(st_t)["narration"]
assert calls == [] and [(p.status, p.error) for p in out.pages] == [("failed", "None: deadline")] * 3
clock = [0.0]
def slow(i):   # 첫 쪽이 200초 걸린 셈: 나머지 쪽은 시작 전에 전체 시간(180초)을 넘긴다
    calls.append(i)
    clock[0] += 200
    return b"ID3s"
tts.set_tts_override(slow)
with patch.object(nr, "_now", lambda: clock[0]), patch.object(nr, "config", replace(one_at_a_time, tts_deadline=180)):
    out = nr.narrate(st_t)["narration"]
assert len(calls) == 1 and [(p.status, p.error) for p in out.pages] == [
    ("completed", None), ("failed", "None: deadline"), ("failed", "None: deadline")]

calls.clear()
def quota(i):
    calls.append(i)
    raise tts.TtsError("quota_exceeded", status=402)
tts.set_tts_override(quota)
with patch.object(nr, "config", one_at_a_time), captured_logs() as logs:
    out = nr.narrate(st_t)["narration"]
assert len(calls) == 1 and [p.error for p in out.pages] == ["402: quota_exceeded", "402: skipped", "402: skipped"]
assert sum("음성 실패" in m for m in logs) == 3

waits: list[int] = []
def flaky(status):
    def fn(i):
        calls.append(i)
        if len(calls) == 1:
            raise tts.TtsError("x", status=status)
        return b"ID3f"
    return fn
one = {**st_t, "story": story_with(pages={1: "1쪽 글이에요."}, cast=["라니"])}
for status, n_calls, ok in [(429, 2, True), (503, 2, True), (None, 2, True), (400, 1, False), (403, 1, False), (422, 1, False)]:
    calls.clear(); waits.clear()
    tts.set_tts_override(flaky(status))
    with patch.object(nr, "_retry_wait", lambda: waits.append(1)):
        out = nr.narrate(one)["narration"]
    assert len(calls) == n_calls and len(waits) == n_calls - 1, (status, calls, waits)
    assert out.pages[0].status == ("completed" if ok else "failed"), status
calls.clear()
tts.set_tts_override(lambda i: calls.append(i) or (_ for _ in ()).throw(tts.TtsError("busy", status=500)))
out = nr.narrate(one)["narration"]
assert len(calls) == 2 and out.pages[0].error == "500: busy"   # 두 번 다 실패하면 끝

# --- 마지막 고치기: 글만 만드는 실행·낭독 꺼짐은 아무것도 부르지 않는다 ---
llm.set_structured_override(boom)
tts.set_tts_override(no_tts)
empty = {"voice_plan": {"cast_types": {}, "cast_voices": {}, "speakers": {}}, "cost": []}
assert nr.assign_voices({"story": story_v1, "skip_images": True}) == empty
assert nr.narrate({**st_t, "skip_images": True}) == {"narration": None, "cost": []}
tts.set_tts_override(None)
with patch.object(tts, "config", SimpleNamespace(elevenlabs_api_key="")):
    assert nr.assign_voices({"story": story_v1}) == empty
llm.set_structured_override(None)

# --- 마지막 고치기: HTTP 응답 다루기 (빈 본문, 짧은 오류, 프로세스 전체 동시 요청 상한) ---
res, _ = run_dialogue([_Resp(b"")])
assert isinstance(res, tts.TtsError) and res.status is None and str(res) == "empty audio"
secret = {"detail": {"status": "quota_exceeded", "message": "라니가 \"비밀 글\" 하고 말했어요"}}
res, _ = run_dialogue([http_error(402, json.dumps(secret, ensure_ascii=False).encode())])
assert nr._err(res) == "402: quota_exceeded" and "라니" not in str(res)
res, _ = run_dialogue([http_error(422, json.dumps({"detail": [{"msg": "라니"}]}, ensure_ascii=False).encode())])
assert nr._err(res) == "422: http_error"
res, _ = run_dialogue([http_error(401, b'{"detail": {"code": "invalid_api_key"}}')])
assert nr._err(res) == "401: invalid_api_key"
assert isinstance(tts._SEM, threading.BoundedSemaphore().__class__)
sem_seen: list[int] = []
free = tts._SEM._value
def held_urlopen(req, timeout=None):
    sem_seen.append(tts._SEM._value)
    raise http_error(402, json.dumps(secret, ensure_ascii=False).encode())
with patch.object(tts, "config", SimpleNamespace(elevenlabs_api_key="k", tts_model="m", tts_timeout=60)), \
     patch.object(urllib.request, "urlopen", held_urlopen), patch.object(nr, "config", one_at_a_time), captured_logs() as logs:
    out = nr.narrate({**st_t, "output_prefix": f"{base}/h/"})["narration"]
assert sem_seen and all(v < free for v in sem_seen) and tts._SEM._value == free   # 요청하는 동안만 자리를 잡는다
assert out.pages[0].error == "402: quota_exceeded" and not any("비밀" in m for m in logs)
assert "[narrate] 1쪽 음성 실패: 402: quota_exceeded" in logs and len(sem_seen) == 1   # 2·3쪽은 차단기로 부르지 않는다

# --- Backend#95: 화면에 보이는 가이드 질문 줄도 해설자로 읽는다 ---
from firstory.schemas import AfterReading, BeforeReading, GuidePrompt, ReadingGuide  # noqa: E402

def guide_q(*pairs):
    return ReadingGuide(synopsis="s", prompts=[GuidePrompt(id=f"q{i}", after_page=a, text=t, purpose="empathy") for i, (a, t) in enumerate(pairs)],
                        before_reading=BeforeReading(intent="i", tips=["t"]), after_reading=AfterReading(bridge_question="b"))

pl = {"cast_types": {"라니": "child_girl"}, "cast_voices": {"라니": "v-rani"}, "speakers": {"2-1": "라니"}}
assert nr.page_inputs(2, '"싫어!"', pl, ["**라니**는 왜 싫었을까요?"]) == [
    {"text": "싫어!", "voice_id": "v-rani"}, {"text": "라니는 왜 싫었을까요?", "voice_id": voices.NARRATOR}]
assert nr.page_inputs(2, "라니는 왔어요.", pl, ["왜 왔을까요?"]) == [   # 해설 + 질문은 기존 규칙대로 한 조각
    {"text": "라니는 왔어요. 왜 왔을까요?", "voice_id": voices.NARRATOR}]

q_calls: list[list[dict]] = []
tts.set_tts_override(lambda i: q_calls.append(i) or b"ID3q")
q_story = story_with(pages={1: "1쪽 글이에요.", 2: '"싫어!" 라니가 말했어요.', 3: "3쪽 글이에요."}, cast=["라니"])
q_plan = {"cast_types": {"라니": "child_girl"}, "cast_voices": {"라니": "v-rani"}, "speakers": {"2-1": "라니"}}
q_st = {"story": q_story, "voice_plan": q_plan, "guide": guide_q((2, "**라니**는 왜 싫었을까요?")), "output_prefix": f"{base}/q1/"}
qn1 = nr.narrate(q_st)["narration"]
assert len(q_calls) == 3
p2 = next(c for c in q_calls if c[0]["voice_id"] == "v-rani")
assert p2[-1] == {"text": "라니가 말했어요. 라니는 왜 싫었을까요?", "voice_id": voices.NARRATOR}   # 해설 뒤에 질문이 붙는다(**는 빠짐)
assert all("싫었을까요" not in i["text"] for c in q_calls if c is not p2 for i in c)   # 1·3쪽엔 질문 없음
# 질문만 바뀌면 그 쪽만 다시 녹음, 1·3쪽은 이전 음성 재사용
q_calls.clear()
q_st2 = {**q_st, "guide": guide_q((2, "라니는 어떤 기분이었을까요?")), "narration": qn1, "output_prefix": f"{base}/q2/"}
qn2 = nr.narrate(q_st2)["narration"]
assert len(q_calls) == 1 and q_calls[0][-1]["text"].endswith("라니는 어떤 기분이었을까요?")
assert qn2.pages[0].path == qn1.pages[0].path and qn2.pages[2].path == qn1.pages[2].path and qn2.pages[1].path == f"{base}/q2/audio/page-02.mp3"
assert qn2.pages[1].text_hash == qn1.pages[1].text_hash   # 말한 사람 재사용 키는 쪽 글만
# 질문이 같으면 아무것도 다시 안 한다
q_calls.clear()
nr.narrate({**q_st2, "narration": qn2, "output_prefix": f"{base}/q3/"})
assert q_calls == []
# assign_voices는 질문 글을 모델에게 보내지 않는다 (system·user 모두)
seen_sys: list[str] = []
llm.set_structured_override(lambda **kw: seen_sys.append(kw["system"] + kw["user"]) or SpeakerAssignment(cast=[], quotes=[]))
nr.assign_voices({**q_st, "guide": guide_q((2, "라니는 왜 싫었을까요?"), (1, "이건 1쪽 질문일까요?"))})
assert seen_sys and all("싫었을까요" not in t and "1쪽 질문" not in t for t in seen_sys)
assert "[1쪽]\n1쪽 글이에요." in seen_sys[0] and "[3쪽]\n3쪽 글이에요." in seen_sys[0]   # 대사 없는 쪽도 문맥으로 같이 보낸다
# 모델이 id를 "[2-1]"처럼 괄호째 돌려줘도 말한 사람이 맞게 들어간다 (진짜 모델이 그렇게 답한 적이 있다)
llm.set_structured_override(lambda **kw: SpeakerAssignment(cast=[], quotes=[QuoteSpeaker(id=" [2-1] ", speaker="라니 ")]))
assert nr.assign_voices(q_st)["voice_plan"]["speakers"] == {"2-1": "라니"}
llm.set_structured_override(None)
tts.set_tts_override(None)

retry_patch.stop()
storage_patch.stop()

print("ALL OK")
