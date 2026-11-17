"""
sample_refresh.py 순수 함수 확인 (API 없음). uv run python evals/sample_refresh_check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from firstory.nodes.layout import MAX_LINE, W, text_width  # noqa: E402
from firstory.schemas import SoundPiece, SoundWord, TextBlock  # noqa: E402
from sample_refresh import SAMPLES, rewrap, same_text, to_front  # noqa: E402

old_story = json.loads((SAMPLES / "tantrum" / "story.json").read_text(encoding="utf-8"))
old = [b["paragraphs"] for b in old_story["pages"][0]["textBlocks"]]

# 지금 글자 크기로 다시 감는다: 38%를 넘는 줄은 띄어쓰기에서 자른다, 글은 그대로
long = [[["미루가 노란 접시를 두 손으로 꼭 잡고 한참 동안 바라보았어요."]]]
assert len(rewrap(long)[0][0]) == 2, rewrap(long)
assert all(text_width(l) <= W * MAX_LINE or " " not in l for b in rewrap(old) for p in b for l in p)
assert same_text(old, rewrap(old)) and same_text(long, rewrap(long))
assert not same_text(old, [[["다른 글."]]])
# 강조 표시와 공백은 빼고 비교한다 (wrap_line이 강조 안에서 자르면 ****가 생긴다)
assert same_text([[["**훌쩍훌쩍** 울었어요."]]], [[["**훌쩍**", "**훌쩍** 울었어요."]]])

# 프론트(Spring 책 응답) 모양: 색·side 대문자, x·y 소수 1자리, owner 없음
tb, sw = to_front([TextBlock(paragraphs=[["가."]], x=10.04, y=8.0, color="dark")],
                  SoundWord(text="훌쩍훌쩍", color="#AA3300", owner="미루",
                            pieces=[SoundPiece(text="훌쩍", x=30.04, y=40.0, side="left"),
                                    SoundPiece(text="훌쩍", x=60.0, y=40.0, side="right")]))
assert tb == [{"paragraphs": [["가."]], "x": 10.0, "y": 8.0, "color": "DARK"}], tb
assert sw == {"text": "훌쩍훌쩍", "color": "#AA3300", "pieces": [
    {"text": "훌쩍", "x": 30.0, "y": 40.0, "side": "LEFT"}, {"text": "훌쩍", "x": 60.0, "y": 40.0, "side": "RIGHT"}]}, sw
assert to_front([], None) == ([], None)

print("sample refresh check ok")
