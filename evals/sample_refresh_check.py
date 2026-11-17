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

from firstory.nodes.layout import H, MAX_LINE, W, piece_size, sound_words, text_width  # noqa: E402
from firstory.schemas import SoundPiece, SoundWord, TextBlock  # noqa: E402
from sample_refresh import SAMPLES, check_story, move_blocks, move_pieces, piece_boxes, export_story, redraw_prompt, rewrap, same_text, to_front  # noqa: E402

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

# 다시 그리기 지시: 같은 장면·인물 + 덩어리 크기·자리
p = redraw_prompt([(700.0, 300.0)], ["left top"])
assert "same characters" in p and "toward the left top" in p, p
assert "evening" in redraw_prompt([(700.0, 300.0)], ["left top"], "It is evening.") and "Change only this" in redraw_prompt([(1.0, 1.0)], ["left top"], "It is evening.")
assert "Change only this" not in p

# 내보내기: 바뀌는 건 textBlocks·soundWord뿐, 검사가 망가진 값을 잡는다
pages = {str(pg["pageNo"]): {"textBlocks": [{**b, "paragraphs": rewrap([b["paragraphs"]])[0]} for b in pg["textBlocks"]],
                             "soundWord": None} for pg in old_story["pages"]}
w_page = next(pg for pg in old_story["pages"] if sound_words(pg["text"]))
w = sound_words(w_page["text"])[0]
pages[str(w_page["pageNo"])]["soundWord"] = {"text": w, "color": "#AA3300", "pieces": [{"text": w.replace(" ", ""), "x": 50.0, "y": 50.0, "side": "CENTER"}]}
new = export_story(old_story, pages)
assert check_story(old_story, new) == [], check_story(old_story, new)
assert new["pages"][0]["soundWord"] is None or isinstance(new["pages"][0]["soundWord"], dict)
assert {k: v for k, v in new.items() if k != "pages"} == {k: v for k, v in old_story.items() if k != "pages"}


def broken(fn):
    b = json.loads(json.dumps(new))
    fn(b)
    return check_story(old_story, b)


assert any("text" in m for m in broken(lambda b: b["pages"][0].update(text=b["pages"][0]["text"] + "!")))
assert any("title" in m for m in broken(lambda b: b.update(title="다른 제목")))
assert broken(lambda b: b["pages"][0].update(textBlocks=[]))
assert broken(lambda b: b["pages"][0]["textBlocks"][0].update(x=120))
assert broken(lambda b: b["pages"][0]["textBlocks"][0].update(paragraphs=[["다른 글."]]))
wi = int(w_page["pageNo"]) - 1
assert broken(lambda b: b["pages"][wi]["soundWord"].update(color="red"))
assert broken(lambda b: b["pages"][wi]["soundWord"].update(pieces=[]))
assert broken(lambda b: b["pages"][wi]["soundWord"]["pieces"][0].update(side="left"))
assert broken(lambda b: b["pages"][wi]["soundWord"]["pieces"][0].update(text="콩"))
assert broken(lambda b: b["pages"][wi]["soundWord"].update(text="콩", pieces=[{"text": "콩", "x": 5, "y": 5, "side": "CENTER"}]))

# 손으로 옮기기: 조각 자리만 바꾸고 말·색·side는 그대로, 개수가 다르거나 0~100 밖이면 거부
sw0 = {"text": "쓰담쓰담", "color": "#FFFFFF", "pieces": [{"text": "쓰담", "x": 45.7, "y": 10.0, "side": "LEFT"}, {"text": "쓰담", "x": 89.8, "y": 10.0, "side": "RIGHT"}]}
moved = move_pieces(sw0, [(30.0, 50.0), (70.0, 55.5)])
assert [(q["x"], q["y"]) for q in moved["pieces"]] == [(30.0, 50.0), (70.0, 55.5)] and moved["color"] == "#FFFFFF"
assert [q["side"] for q in moved["pieces"]] == ["LEFT", "RIGHT"] and sw0["pieces"][0]["x"] == 45.7
one = move_pieces(sw0, [(33.0, 60.0)])   # 두 조각 → 자리 하나면 한 조각으로 합친다 (가운데)
assert one["pieces"] == [{"text": "쓰담쓰담", "x": 33.0, "y": 60.0, "side": "CENTER"}] and one["text"] == "쓰담쓰담"
for bad_xy in ([(30.0, 50.0)] * 3, [(30.0, 50.0), (101.0, 5.0)]):
    try:
        move_pieces(sw0, bad_xy)
        raise AssertionError(bad_xy)
    except ValueError:
        pass

tb0 = [{"paragraphs": [["가."]], "x": 54.0, "y": 50.0, "color": "DARK"}]
assert move_blocks(tb0, [(25.0, 6.0)]) == [{"paragraphs": [["가."]], "x": 25.0, "y": 6.0, "color": "DARK"}] and tb0[0]["x"] == 54.0
try:
    move_blocks(tb0, [(25.0, 6.0), (1.0, 1.0)])
    raise AssertionError("count")
except ValueError:
    pass

# 다시 칠하기: 조각 가운데(%) → 조각 상자(px x, y, w, h)
_pw, _ph = piece_size("쓰담쓰담")
assert piece_boxes({"text": "쓰담쓰담", "color": "#000000", "pieces": [{"text": "쓰담쓰담", "x": 50.0, "y": 25.0, "side": "CENTER"}]}) == [
    (W * 0.5 - _pw / 2, H * 0.25 - _ph / 2, _pw, _ph)]

print("sample refresh check ok")
