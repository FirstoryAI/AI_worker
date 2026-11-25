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

from firstory import tts, voices  # noqa: E402
from firstory.schemas import CostEntry, Narration, PageAudio  # noqa: E402

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

print("ALL OK")
