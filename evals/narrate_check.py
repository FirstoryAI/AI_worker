"""
다중 음성 낭독(TTS) 배선 확인. API 없이 돈다. (uv run python evals/narrate_check.py)
ElevenLabs는 절대 실제로 부르지 않는다: tts.set_tts_override 또는 tts.config 패치만 쓴다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstory import llm, tts, voices  # noqa: E402
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

print("ALL OK")
