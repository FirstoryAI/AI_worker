"""
API 없이 글 덩어리 계산(줄·덩어리·크기·자리)을 확인. (uv run python evals/layout_run.py)
nodes/layout.py 의 순수 함수만 부른다. 합성 그림으로 Busy·settle 도 확인한다.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firstory.nodes.layout import (  # noqa: E402
    BAND, BUSY_LIMIT, EDGE_X, EDGE_Y, FOLD, FONT_PX, FONT_RATIO, GAP, H, MAX_LINE, W,
    Busy, block_size, build_blocks, calmest, calmest_pick, side_of, chunk_page, merge, normalize_chunks, place_page, settle, split_lines, text_width, wrap_line,
)
from firstory import llm, mock  # noqa: E402
from firstory.schemas import BlockSpot, CharacterBox, OwnerBox, TextChunking, TextPlacement  # noqa: E402

# ── 줄 나누기 ──
# 대사 하나는 한 줄 (#77): 따옴표 안의 마침표·줄바꿈에서는 자르지 않는다
assert split_lines('라라가 골랐어요. "어제 그 말 들으니 속상했어. 나는 같이 그리고 싶었어."') == [
    '라라가 골랐어요.', '"어제 그 말 들으니 속상했어. 나는 같이 그리고 싶었어."']
assert split_lines('나루가 블록을 잡았어요.\n"속상했어. 같이 이렇게 놀고 싶어."\n미소가 고개를 끄덕였어요.') == [
    '나루가 블록을 잡았어요.', '"속상했어. 같이 이렇게 놀고 싶어."', '미소가 고개를 끄덕였어요.']
assert split_lines('"어제는 혼자 하고 싶었어.\n라라가 싫어서 간 건 아니야." 미나가 웃었어요.') == [
    '"어제는 혼자 하고 싶었어. 라라가 싫어서 간 건 아니야."', '미나가 웃었어요.']
assert split_lines('“좋아. 같이 하자.” 둘은 웃었어요.') == ['“좋아. 같이 하자.”', '둘은 웃었어요.']
assert split_lines('"알겠어…" 미나가 말했어요.') == ['"알겠어…" 미나가 말했어요.']
assert split_lines("하루가 **토닥토닥** 했어요.\n잘 자.") == ["하루가 **토닥토닥** 했어요.", "잘 자."]
assert split_lines("그래...  좋아.") == ["그래...  좋아."]                      # 말줄임표는 끊지 않음
long = '"어제는 내 그림을 혼자 끝내고 싶었어. 라라가 싫어서 간 건 아니야."'
wrapped = wrap_line(long)
assert len(wrapped) >= 2 and " ".join(wrapped) == long
assert all(text_width(l) <= W * MAX_LINE for l in wrapped)
assert wrap_line("짧은 줄.") == ["짧은 줄."]
emph = "라라는 **아주 아주 아주 아주 소중한 그림을 아주 오래오래 그리고 싶어서 정말 정말 정말 열심히 했던** 그 마음이 싫었어요 라고 말했어요."
ew = wrap_line(emph)
assert len(ew) >= 2 and all(l.count("**") % 2 == 0 for l in ew), ew                  # 줄마다 ** 짝이 맞음
assert " ".join(ew).replace("**", "") == emph.replace("**", ""), ew                    # 글자는 그대로
assert all(text_width(l) <= W * MAX_LINE for l in ew)
assert ew[0].endswith("**") and ew[1].startswith("**"), ew                              # 갈라진 곳에서 닫고 다시 연다
assert text_width("**토닥**") == text_width("토닥")                             # ** 는 폭에서 뺌

# ── 덩어리 정리 ──
lines = ['미나가 라라를 보았어요.', '"어제는 내 그림을 혼자 끝내고 싶었어.', '라라가 싫어서 간 건 아니야."', '라라는 꽃을 그렸어요.']
assert normalize_chunks(4, [[[0, 1], [2]], [[3]]], lines) == [[[0, 1, 2]], [[3]]]    # 대사 중간 문단 끊김 → 붙임
assert normalize_chunks(4, [[[0, 1]], [[2, 3]]], lines) == [[[0, 1, 2]], [[3]]]      # 대사 중간 덩어리 끊김 → 붙임
assert normalize_chunks(4, [[[0]], [[2, 3]]], lines) == [[[0, 1, 2, 3]]]             # 줄 빠짐
assert normalize_chunks(4, [[[0]], [[1]], [[2, 3]]], lines) == [[[0, 1, 2, 3]]]      # 3덩어리
assert normalize_chunks(4, [[[1, 0]], [[2, 3]]], lines) == [[[0, 1, 2, 3]]]          # 순서 바뀜
assert normalize_chunks(4, [[[0], [1, 2]], [[3]]], lines) == [[[0], [1, 2]], [[3]]]  # 멀쩡하면 그대로
assert normalize_chunks(3, [[[0, 1]], [[2]]], ["가.", "나.", "다."]) == [[[0, 1]], [[2]]]
assert normalize_chunks(2, [[[0]], [[1]]], ['"가.', '나."']) == [[[0, 1]]]           # 덩어리가 비면 하나로
assert normalize_chunks(2, [[[0]], [[1]]]) == [[[0]], [[1]]]                         # 줄 글 없이도 부를 수 있음
assert normalize_chunks(3, [[[0, 1], [2]], [[3]]], lines[:3]) == [[[0, 1, 2]]]       # 범위 밖 번호
assert normalize_chunks(1, [[[0]]], ["가."]) == [[[0]]]

blocks = build_blocks(lines, [[[0], [1, 2]], [[3]]])
assert len(blocks) == 2 and len(blocks[0]) == 2 and blocks[1] == [["라라는 꽃을 그렸어요."]]
assert blocks[0][0] == [lines[0]] and blocks[0][1][0] == lines[1]
assert merge(blocks) == [blocks[0] + blocks[1]]

w, h = block_size([["가나다"], ["라마"]]); assert h == (2 + 0.6) * FONT_PX * 1.55
assert abs(w - text_width("가나다")) < 1e-9
assert block_size([["가", "나", "다"]])[1] == 3 * FONT_PX * 1.55


# ── 합성 그림: 왼쪽 위(x 5~45%, y 7~40%)만 줄무늬, 나머지는 흰 바탕 ──
def png(img: Image.Image) -> bytes:
    buf = io.BytesIO(); img.save(buf, "PNG"); return buf.getvalue()


def stripes(box_pct: tuple[float, float, float, float] | None, size=(W, H)) -> Image.Image:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    sx, sy = size[0] / 100, size[1] / 100
    x0, y0, x1, y1 = box_pct or (0, 0, 100, 100)
    step = 24 * size[0] // W
    for x in range(int(x0 * sx), int(x1 * sx), step):
        d.rectangle([x, int(y0 * sy), x + step // 2 - 1, int(y1 * sy)], fill=(40, 40, 40))
    return img


busy = Busy(png(stripes((5, 7, 45, 40))))
assert busy.at(0.05 * W, 0.7 * H, 0.2 * W, 0.2 * H) < 1                               # 흰 바탕
assert busy.at(0.10 * W, 0.12 * H, 0.2 * W, 0.2 * H) > BUSY_LIMIT                     # 줄무늬
assert abs(Busy(png(stripes((5, 7, 45, 40), (960, 544)))).at(0.10 * W, 0.12 * H, 0.2 * W, 0.2 * H)
           - busy.at(0.10 * W, 0.12 * H, 0.2 * W, 0.2 * H)) < 4                       # 다른 크기 그림도 맞춰 줄임

blk = [["첫째 줄이에요.", "둘째 줄이에요.", "셋째 줄이에요."]]
bw, bh = block_size(blk)
gap_px = GAP * W


def px(spot):  # % -> px
    return spot["x"] / 100 * W, spot["y"] / 100 * H


def page(spot, bw):
    return 0 if px(spot)[0] + bw / 2 < W / 2 else 1


def check_one(spot, bw, bh):
    """여백·띠·복잡도를 모두 지켰는지"""
    x, y = px(spot)
    assert EDGE_X / 100 * W - 1 <= x and x + bw <= W * (1 - EDGE_X / 100) + 1, spot
    mid = W / 2
    if x + bw / 2 < mid: assert x + bw <= mid - FOLD / 100 * W + 1, spot
    else: assert x >= mid + FOLD / 100 * W - 1, spot
    top = EDGE_Y / 100 * H - 1 <= y <= BAND / 100 * H + 1
    bot = (100 - BAND) / 100 * H - 1 <= y + bh <= (100 - EDGE_Y) / 100 * H + 1
    assert top or bot, spot
    pad = 0.03 * W
    assert busy.at(x - pad, y - pad, bw + 2 * pad, bh + 2 * pad) <= BUSY_LIMIT + 0.5, spot


# 1) AI 자리가 줄무늬 위 → 줄무늬 밖 띠 안으로 옮김
out = settle(busy, [blk], [{"x": 6, "y": 8, "color": "dark"}])
assert out and len(out) == 1 and out[0]["color"] == "dark", out
check_one(out[0], bw, bh)
assert out[0] != {"x": 6, "y": 8, "color": "dark"}
assert isinstance(out[0]["x"], float) and out[0]["x"] == round(out[0]["x"], 1)

# 2) AI 자리가 띠 밖(가운데 높이) → 띠로 옮김
out = settle(busy, [blk], [{"x": 55, "y": 45, "color": "light"}])
assert out and out[0]["color"] == "dark"          # 글자색은 AI 답이 아니라 바탕 밝기 (흰 바탕 → dark, #77)
check_one(out[0], bw, bh)
assert out[0]["y"] != 45

# 2-1) 이미 괜찮은 자리는 그대로 둔다
out = settle(busy, [blk], [{"x": 55, "y": 8, "color": "dark"}])
assert out == [{"x": 55.0, "y": 8.0, "color": "dark"}], out

# 2-2) 여백 밖으로 붙은 자리는 면 안으로 민다 (오른쪽 가장자리에 붙임 → 안쪽으로)
out = settle(busy, [blk], [{"x": 80, "y": 8, "color": "dark"}])
assert out and out[0]["x"] / 100 * W + bw <= W * (1 - EDGE_X / 100) + 1, out
check_one(out[0], bw, bh)

# 3) 덩어리 2개: 1 이 오른쪽 면 위, 2 가 왼쪽 면 → 1 은 왼쪽 면, 2 는 오른쪽 면으로 옮김 (#95)
assert side_of(0, 2) == 0 and side_of(1, 2) == 1 and side_of(0, 1) is None and side_of(2, 3) is None
blk2 = [["넷째 줄이에요.", "다섯째 줄이에요."]]
bw2, bh2 = block_size(blk2)
s1 = {"x": 55, "y": 8, "color": "dark"}
out = settle(busy, [blk, blk2], [s1, {"x": 8, "y": 70, "color": "light"}])
assert out and len(out) == 2, out
check_one(out[0], bw, bh)
check_one(out[1], bw2, bh2)
assert page(out[0], bw) == 0 and page(out[1], bw2) == 1, out
assert out[1]["color"] == "dark"

# 3-1) 순서를 지키는 두 자리(왼쪽 면 위 → 오른쪽 면 아래)는 그대로 둔다
out = settle(busy, [blk, blk2], [{"x": 8, "y": 70, "color": "dark"}, {"x": 55, "y": 75, "color": "light"}])
assert out == [{"x": 8.0, "y": 70.0, "color": "dark"}, {"x": 55.0, "y": 75.0, "color": "dark"}], out
for o, (b_w, b_h) in zip(out, [(bw, bh), (bw2, bh2)]):
    check_one(o, b_w, b_h)
assert (page(out[0], bw), out[0]["y"]) < (page(out[1], bw2), out[1]["y"])

# 3-2) 두 덩어리가 서로 겹치지 않고 2% 이상 떨어져 있다
out = settle(busy, [blk, blk2], [{"x": 55, "y": 8, "color": "dark"}, {"x": 55, "y": 12, "color": "dark"}])
assert out and len(out) == 2
(ax, ay), (bx, by) = px(out[0]), px(out[1])
sep_x = max(ax - (bx + bw2), bx - (ax + bw))
sep_y = max(ay - (by + bh2), by - (ay + bh))
assert max(sep_x, sep_y) >= gap_px - 1, out
assert page(out[0], bw) == 0 and page(out[1], bw2) == 1, out                         # 둘 다 오른쪽이라 답해도 1 은 왼쪽 면 (#95)

# 3-3) 둘 다 왼쪽 면 아래라고 답하면 1 은 그대로, 2 는 오른쪽 면으로 (#95)
out = settle(busy, [blk, blk2], [{"x": 8, "y": 70, "color": "dark"}, {"x": 8, "y": 80, "color": "dark"}])
assert out and out[0] == {"x": 8.0, "y": 70.0, "color": "dark"}, out
assert page(out[1], bw2) == 1, out
check_one(out[1], bw2, bh2)

# 4) 픽셀로 답한 자리는 %로 바꾼다
out = settle(busy, [blk], [{"x": 1037, "y": 800, "color": "dark"}])
assert out and out[0] == {"x": round(1037 / W * 100, 1), "y": round(800 / H * 100, 1), "color": "dark"}, out

# 5) 그림 전체가 줄무늬면 자리가 없다
full = Busy(png(stripes(None)))
assert settle(full, [blk], [{"x": 6, "y": 8, "color": "dark"}]) is None
assert settle(full, [blk, blk2], [{"x": 6, "y": 8, "color": "dark"}, {"x": 55, "y": 8, "color": "dark"}]) is None

# 6) 한쪽 면 전체가 줄무늬면 반대쪽 면에서 찾는다
left_full = Busy(png(stripes((0, 0, 50, 100))))
out = settle(left_full, [blk], [{"x": 8, "y": 8, "color": "dark"}])
assert out and out[0]["x"] / 100 * W >= W / 2, out

# 6-1) 두 덩어리는 반대 면으로 넘어가지 않는다: 오른쪽 면이 다 줄무늬면 settle은 None, calmest는 그래도 양쪽에 하나씩 (#95)
right_full = Busy(png(stripes((50, 0, 100, 100))))
assert settle(right_full, [blk, blk2], [{"x": 8, "y": 70, "color": "dark"}, {"x": 55, "y": 75, "color": "dark"}]) is None
out = calmest(right_full, [blk, blk2])
assert out and page(out[0], bw) == 0 and page(out[1], bw2) == 1, out

# 6-2) 조용한 곳이 없을 때 나눌지 합칠지: 나눈 자리 중 더 복잡한 쪽이 합친 자리보다 복잡하면 합친다 (#95)
#      오른쪽 면이 다 줄무늬면 나누면 2 가 줄무늬 위 → 합친 한 덩어리를 왼쪽 면에
bl, out = calmest_pick(right_full, [blk, blk2])
assert len(bl) == 1 and bl[0] == blk + blk2 and len(out) == 1, (bl, out)
assert page(out[0], block_size(bl[0])[0]) == 0, out
#      어디나 똑같이 조용하면(같으면) 나눈다
white = Busy(png(Image.new("RGB", (W, H), "white")))
bl, out = calmest_pick(white, [blk, blk2])
assert bl == [blk, blk2] and page(out[0], bw) == 0 and page(out[1], bw2) == 1, (bl, out)
#      한 덩어리는 calmest 그대로
assert calmest_pick(white, [blk]) == ([blk], calmest(white, [blk]))


# 7) 어디도 기준을 못 넘으면 settle은 None, calmest는 가장 덜 복잡한 곳 (오른쪽 아래만 옅은 줄무늬)
def stripes_two(soft_box: tuple[float, float, float, float], soft=(200, 200, 200), bg="white") -> Image.Image:
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    sx, sy = W / 100, H / 100
    for x in range(0, W, 24):
        d.rectangle([x, 0, x + 11, H], fill=(40, 40, 40))
    x0, y0, x1, y1 = soft_box
    d.rectangle([int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy)], fill=bg)
    for x in range(int(x0 * sx), int(x1 * sx), 24):
        d.rectangle([x, int(y0 * sy), x + 11, int(y1 * sy)], fill=soft)
    return img


soft_br = Busy(png(stripes_two((52, 55, 100, 100))))
assert settle(soft_br, [blk], [{"x": 6, "y": 8, "color": "dark"}]) is None
out = calmest(soft_br, [blk])
assert out and len(out) == 1, out
x, y = px(out[0])
assert x >= W * 0.52 and y >= H * 0.55, out                                    # 옅은 곳(오른쪽 아래)
assert soft_br.at(x, y, bw, bh) < soft_br.at(0.05 * W, 0.07 * H, bw, bh)       # 기본 자리보다 조용함
check_band = (100 - BAND) / 100 * H - 1 <= y + bh <= (100 - EDGE_Y) / 100 * H + 1
assert check_band and x + bw <= W * (1 - EDGE_X / 100) + 1, out                 # 띠·여백은 지킴
assert out[0]["color"] == "dark"                                               # 밝은 바탕 → 진한 글자

# 7-1) 두 덩어리도 읽는 순서·간격을 지키고, 어두운 바탕이면 흰 글자
dark_bg = Busy(png(stripes_two((0, 0, 100, 100), soft=(70, 70, 90), bg=(50, 50, 60))))
out = calmest(dark_bg, [blk, blk2])
assert out and len(out) == 2, out
assert page(out[0], bw) == 0 and page(out[1], bw2) == 1, out                         # 1 은 왼쪽, 2 는 오른쪽 면 (#95)
assert (page(out[0], bw), out[0]["y"]) < (page(out[1], bw2), out[1]["y"]), out
assert all(o["color"] == "light" for o in out), out
# AI가 dark라고 답해도 어두운 바탕이면 흰 글자 (#77)
dark_out = settle(dark_bg, [blk], [{"x": 55, "y": 8, "color": "dark"}])
assert dark_out and dark_out[0]["color"] == "light", dark_out
# 라벤더 벽: 채널 평균은 150을 넘지만 대비는 흰 글자가 낫다 → light. 밝은 회색은 dark (#77)
from firstory.nodes.layout import text_color  # noqa: E402
lavender = Busy(png(Image.new("RGB", (W, H), (149, 142, 168))))
assert text_color(lavender, 200, 80, bw, bh) == "light"
assert text_color(Busy(png(Image.new("RGB", (W, H), (190, 190, 190)))), 200, 80, bw, bh) == "dark"
(ax, ay), (bx, by) = px(out[0]), px(out[1])
assert max(max(ax - (bx + bw2), bx - (ax + bw)), max(ay - (by + bh2), by - (ay + bh))) >= gap_px - 1, out

# ── 덩어리 나누기 호출 (LLM 가짜) ──
calls: list[dict] = []


def fake_with(answer):
    """answer(kw) → 스키마 객체. 부른 인자를 calls 에 쌓는다."""
    def fn(**kw):
        calls.append(kw)
        if isinstance(answer, Exception):
            raise answer
        return answer(kw) if callable(answer) else answer
    return fn


text = "미나가 라라를 보았어요.\n라라는 꽃을 그렸어요.\n미나는 웃었어요. 둘은 함께 그렸어요."
llm.set_structured_override(fake_with(TextChunking(blocks=[[[0, 1]], [[2, 3]]])))
ls, cks, costs = chunk_page(text)
assert ls == ["미나가 라라를 보았어요.", "라라는 꽃을 그렸어요.", "미나는 웃었어요.", "둘은 함께 그렸어요."], ls
assert cks == [[["미나가 라라를 보았어요.", "라라는 꽃을 그렸어요."]], [["미나는 웃었어요.", "둘은 함께 그렸어요."]]], cks
assert [c.node for c in costs] == ["layout:chunk"] and len(calls) == 1
assert calls[0]["schema"] is TextChunking and "0: 미나가 라라를 보았어요." in calls[0]["system"] and "{{" not in calls[0]["system"]
assert "image" not in calls[0] or calls[0]["image"] is None

# 모든 줄을 한 번씩 쓰지 않은 답 → 한 덩어리 한 문단
llm.set_structured_override(fake_with(TextChunking(blocks=[[[0, 1]], [[2]]])))
_, cks, _ = chunk_page(text)
assert cks == [[ls]], cks
# 따옴표 사이는 붙인다 (lines 를 넘겨 normalize 를 부른다)
q = '라라가 말했어요.\n"어제는 혼자 하고 싶었어.\n라라가 싫어서 간 건 아니야."\n미나가 웃었어요.'
llm.set_structured_override(fake_with(TextChunking(blocks=[[[0], [1]], [[2]]])))
ql, cks, _ = chunk_page(q)
assert ql == ['라라가 말했어요.', '"어제는 혼자 하고 싶었어. 라라가 싫어서 간 건 아니야."', '미나가 웃었어요.'], ql   # 대사는 한 줄 (#77)
assert [" ".join(p) for c in cks for p in c] == ql   # 긴 대사는 wrap_line이 자를 수 있어도 한 문단에 남는다
# 38% 넘는 긴 줄은 build_blocks 가 자른다
longq = '"어제는 내 그림을 혼자 끝내고 싶었어. 라라가 싫어서 간 건 아니야."'
llm.set_structured_override(fake_with(TextChunking(blocks=[[[0, 1]]])))
_, cks, _ = chunk_page(longq + "\n좋아요.")
assert all(text_width(l) <= W * MAX_LINE for c in cks for p in c for l in p)

# 한 줄이면 LLM 을 부르지 않는다
calls.clear()
llm.set_structured_override(fake_with(TextChunking(blocks=[[[0]]])))
ls, cks, costs = chunk_page("포포는 깡충 뛰었어요.")
assert calls == [] and ls == ["포포는 깡충 뛰었어요."] and cks == [[["포포는 깡충 뛰었어요."]]] and costs == []
assert chunk_page("") == ([], [], [])
# 부르다 예외가 나도 한 덩어리로 간다
llm.set_structured_override(fake_with(RuntimeError("boom")))
ls, cks, costs = chunk_page(text)
assert cks == [[ls]] and costs == []

# ── 자리 찾기 호출 ──
img = png(stripes(None))
blk_a = [["첫째 줄이에요.", "둘째 줄이에요."]]
blk_b = [["셋째 줄이에요."]]
calls.clear()
llm.set_structured_override(fake_with(TextPlacement(blocks=[BlockSpot(x=6, y=8, color="dark"), BlockSpot(x=55.5, y=70, color="light")])))
spots, chars0, _, costs = place_page(img, [blk_a, blk_b])
assert spots == [{"x": 6.0, "y": 8.0, "color": "dark"}, {"x": 55.5, "y": 70.0, "color": "light"}], spots
assert chars0 == [] and [c.node for c in costs] == ["layout:place"]
assert calls[0]["schema"] is TextPlacement and "{{" not in calls[0]["system"]
assert calls[0]["image"] != img and "눈금" in calls[0]["system"] and "characters" in calls[0]["system"]   # 모든 쪽에 눈금·캐릭터 칸 (#104)
assert "1번 덩어리" in calls[0]["system"] and "2번 덩어리" in calls[0]["system"]
w1, h1 = block_size(blk_a)
assert f"가로 약 {w1 / W * 100:.0f}%" in calls[0]["system"] and f"세로 약 {h1 / H * 100:.0f}%" in calls[0]["system"]


def placed(*spots):
    llm.set_structured_override(fake_with(TextPlacement.model_construct(blocks=[BlockSpot.model_construct(x=a, y=b, color=c) for a, b, c in spots])))
    return place_page(img, [blk_a])[0]


# place tolerates bad answers
assert placed((1037, 800, "dark")) == [{"x": 1037 / W * 100, "y": 800 / H * 100, "color": "dark"}]   # 픽셀 → %
assert placed((1037, 8, "dark")) == [{"x": 1037 / W * 100, "y": 8.0, "color": "dark"}]               # 축마다 따로
assert placed((6, 800, "dark")) == [{"x": 6.0, "y": 800 / H * 100, "color": "dark"}]
assert placed((6, 8, "gray")) == [{"x": 6.0, "y": 8.0, "color": "dark"}]                              # 색 이상 → dark
assert placed((float("nan"), 8, "dark")) == [] and placed((6, float("inf"), "dark")) == []
llm.set_structured_override(fake_with(TextPlacement(blocks=[BlockSpot(x=6, y=8, color="dark")])))
assert place_page(img, [blk_a, blk_b])[0] == []                                                      # 개수 다름
llm.set_structured_override(fake_with(TextPlacement(blocks=[])))
assert place_page(img, [blk_a])[0] == []
llm.set_structured_override(fake_with(RuntimeError("글자 내용이 들어 있어도 로그엔 안 남는다")))
assert place_page(img, [blk_a]) == ([], [], None, [])                                                          # 예외 → []
llm.set_structured_override(fake_with(lambda kw: type("Bad", (), {"blocks": [type("S", (), {"x": "abc", "y": None, "color": "dark"})()]})()))
assert place_page(img, [blk_a])[0] == []                                                             # 숫자 아님
assert place_page(img, []) == ([], [], None, [])                                                               # 덩어리 없으면 부르지 않음

# 캐릭터 칸 (#104): 맨 위 characters를 모든 쪽에서 받는다. 이상한 칸은 그 칸만 뺀다
_ob = lambda *v: OwnerBox(x0=v[0], y0=v[1], x1=v[2], y1=v[3])  # noqa: E731
llm.set_structured_override(fake_with(TextPlacement(blocks=[BlockSpot(x=6, y=8, color="dark")],
                                                    characters=[CharacterBox(name="초코", box=_ob(35, 30, 60, 85))])))
assert place_page(img, [blk_a])[1] == [("초코", (35.0, 30.0, 60.0, 85.0))]
llm.set_structured_override(fake_with(TextPlacement.model_construct(blocks=[BlockSpot(x=6, y=8, color="dark")], characters=[
    CharacterBox.model_construct(name="x", box=_ob(60, 10, 50, 20)), CharacterBox.model_construct(name="y", box=_ob(10, 10, 20, 180)),
    CharacterBox(name="모아", box=_ob(10, 30, 30, 85))])))
assert place_page(img, [blk_a])[1] == [("모아", (10.0, 30.0, 30.0, 85.0))]
llm.set_structured_override(fake_with(TextPlacement.model_construct(blocks=[BlockSpot(x=6, y=8, color="dark")])))
assert place_page(img, [blk_a])[1] == []                                                                    # characters 없음
calls.clear()
llm.set_structured_override(fake_with(TextPlacement(blocks=[BlockSpot(x=6, y=8, color="dark")])))
place_page(img, [blk_a], grid=False)
assert calls[0]["image"] == img and "눈금" not in calls[0]["system"]

# mock 모드 배선: 진짜 fake_structured 가 두 스키마를 모두 답한다
llm.set_structured_override(mock.fake_structured)
ls, cks, _ = chunk_page(text)
assert cks == [[ls]], cks
assert place_page(img, [blk_a, blk_b])[0] == [{"x": 5.0, "y": 7.0, "color": "dark"}] * 2
assert place_page(img, [blk_a])[1] == []   # mock: 별표 없는 쪽은 칸 없음
llm.set_structured_override(None)

# structured_image 가 Responses API 에 input_image(data URL, detail high)를 싣는다 (진짜 호출 경로, 클라이언트만 가짜)
seen: dict = {}


class _Res:
    output_parsed = TextPlacement(blocks=[BlockSpot(x=1, y=2, color="light")])
    usage = None


class _Responses:
    def parse(self, **kw):
        seen.update(kw)
        return _Res()


class _Client:
    responses = _Responses()


llm._client = _Client()
obj, cost = llm.structured_image(node="n", model="m", schema=TextPlacement, system="S", user="U", image=img, reasoning="low")
assert obj.blocks[0].x == 1 and cost.node == "n" and seen["reasoning"] == {"effort": "low"} and seen["text_format"] is TextPlacement
part = seen["input"][1]["content"]
assert part[0] == {"type": "input_text", "text": "U"} and part[1]["type"] == "input_image" and part[1]["detail"] == "high"
assert part[1]["image_url"].startswith("data:image/png;base64,") and seen["input"][0] == {"role": "system", "content": "S"}
llm._client = None

print("layout ok")

# 7-2) calmest는 거리보다 복잡도: 왼쪽 위(조금 복잡)보다 멀리 있는 왼쪽 아래(조금 더 조용)를 고른다
import numpy as np  # noqa: E402
import firstory.nodes.layout as _L  # noqa: E402


def two_soft() -> Image.Image:
    img = stripes_two((0, 0, 50, 45), soft=(215, 215, 215))
    d = ImageDraw.Draw(img)
    sx, sy = W / 100, H / 100
    d.rectangle([0, int(55 * sy), int(50 * sx), H], fill="white")
    for x in range(0, int(50 * sx), 24):
        d.rectangle([x, int(55 * sy), x + 11, H], fill=(222, 222, 222))
    return img


soft2 = Busy(png(two_soft()))
out = calmest(soft2, [blk])
x, y = px(out[0])
assert y > H / 2, out                                                            # 아래 띠
grid = [(float(gx), float(gy)) for page in (0, 1) for (ylo, yhi) in _L._y_bands(bh)
        for gy in np.arange(ylo, yhi + 1e-6, _L.GRID) for gx in np.arange(*_L._x_range(page, bw)[:1], _L._x_range(page, bw)[1] + 1e-6, _L.GRID)]
best = min(_L._score(soft2, gx, gy, bw, bh) for gx, gy in grid)
assert _L._score(soft2, x, y, bw, bh) <= best + 0.05, (out, best)              # 두 면을 통틀어 가장 조용함
print("calmest ok")

# ── 이전 배치가 지금 글과 맞나 (_stale) — 대사를 쪼갠 옛 배치는 다시 한다 (#77) ──
from types import SimpleNamespace  # noqa: E402

from firstory.nodes.illustrate import _stale  # noqa: E402
from firstory.schemas import PageImage, TextBlock  # noqa: E402

page = SimpleNamespace(text='나루가 웃었어요.\n"속상했어. 같이 놀고 싶어."')
split_old = PageImage(order=7, path="k", status="completed", text_blocks=[
    TextBlock(paragraphs=[["나루가 웃었어요.", '"속상했어.', '같이 놀고 싶어."']], x=5, y=7, color="dark")])
one_line = PageImage(order=7, path="k", status="completed", text_blocks=[
    TextBlock(paragraphs=[["나루가 웃었어요."]], x=5, y=7, color="dark"),
    TextBlock(paragraphs=[['"속상했어. 같이 놀고 싶어."']], x=55, y=80, color="dark")])
assert _stale(page, split_old)            # 글은 같아도 대사가 쪼개져 있으면 배치만 다시
assert not _stale(page, one_line)         # 덩어리·문단이 나뉘어도 줄이 같으면 그대로
assert not _stale(page, PageImage(order=7, status="failed"))
print("stale ok")

# ── 의성어 (#92) ──
from firstory.llm import prompt  # noqa: E402,F401
from firstory.nodes.layout import (  # noqa: E402
    SFX_FOLD, SfxAsk, _closer_to_source, _others, piece_size, place_word, short_look, sound_words,
)
from firstory.schemas import CharacterBox, OwnerBox, SoundWord, TextPlacementWithWord, WordSpot  # noqa: E402

assert sound_words("미루가 **훌쩍훌쩍** 울었어요.") == ["훌쩍훌쩍"]
assert sound_words("**톡** 치고 ** 냠냠 **") == ["톡", "냠냠"]
assert sound_words("별표 없음.") == []
assert short_look("A small white rabbit with long ears. Wears a yellow apron.") == "A small white rabbit with long ears"
assert len(short_look("x" * 300)) == 120

# place_page: 별표 없는 쪽은 지금 호출 그대로
calls.clear()
llm.set_structured_override(fake_with(TextPlacement(blocks=[BlockSpot(x=6, y=8, color="dark")])))
spots, _, wspot, costs = place_page(img, [blk_a])
assert wspot is None and calls[0]["schema"] is TextPlacement and "의성어" not in calls[0]["system"]
sys0, user0 = calls[0]["system"], calls[0]["user"]

# 별표 있는 쪽: 의성어 단락 + 의성어 스키마. AI는 근원·캐릭터 칸만 답한다 (#102)
ask = SfxAsk(word="데굴데굴", text="초코는 옆에서 자동차를 **데굴데굴** 굴렸어요.", cast=[("초코", "A small hedgehog")])
ob = lambda *v: OwnerBox(x0=v[0], y0=v[1], x1=v[2], y1=v[3])  # noqa: E731
good = WordSpot(owner="초코", source_kind="object", source_box=ob(40, 70, 48, 78))
good_chars = [CharacterBox(name="초코", box=ob(35, 30, 60, 85)), CharacterBox(name="모아", box=ob(10, 30, 30, 85))]
calls.clear()
llm.set_structured_override(fake_with(TextPlacementWithWord(blocks=[BlockSpot(x=6, y=8, color="dark")], characters=good_chars, sound_word=good)))
spots, wchars, wspot, costs = place_page(img, [blk_a], ask)
assert spots == [{"x": 6.0, "y": 8.0, "color": "dark"}] and [c.node for c in costs] == ["layout:place"]
assert wchars == wspot["chars"]                                                  # 의성어도 맨 위 칸을 쓴다 (#104)
assert wspot == {"owner": "초코", "kind": "object", "source": (40.0, 70.0, 48.0, 78.0),
                 "chars": [("초코", (35.0, 30.0, 60.0, 85.0)), ("모아", (10.0, 30.0, 30.0, 85.0))]}, wspot
assert calls[0]["schema"] is TextPlacementWithWord
sysmsg = calls[0]["system"]
assert all(s in sysmsg for s in ("데굴데굴", "초코", "A small hedgehog", "source_kind", "자동차")) and "{{" not in sysmsg
assert "말 크기" not in sysmsg
assert sysmsg.startswith(sys0) and calls[0]["user"].startswith(user0)   # 지금 지시 뒤에 붙일 뿐


def wplaced(spot, chars=good_chars):
    llm.set_structured_override(fake_with(TextPlacementWithWord.model_construct(
        blocks=[BlockSpot(x=6, y=8, color="dark")], characters=chars, sound_word=spot)))
    return place_page(img, [blk_a], ask)[2]


bad_char = [CharacterBox.model_construct(name="x", box=ob(60, 10, 50, 20)), good_chars[1]]
assert wplaced(good, bad_char)["chars"] == [("모아", (10.0, 30.0, 30.0, 85.0))]                 # 뒤집힌 칸만 뺀다
assert wplaced(good, [])["chars"] == []
assert wplaced(good.model_copy(update={"source_box": ob(50, 10, 40, 20)})) is None              # 근원 칸이 뒤집힘
assert wplaced(good.model_copy(update={"source_box": OwnerBox.model_construct(x0=50, y0=float("nan"), x1=60, y1=80)})) is None
assert wplaced(good.model_copy(update={"source_box": ob(50, 30, 60, 180)})) is None              # 0~100 밖
assert wplaced(WordSpot.model_construct(owner="a", source_kind="hand", source_box=ob(1, 1, 2, 2))) is None
assert wplaced(WordSpot.model_construct(owner="a", source_kind="face")) is None   # 근원 칸 없음
assert wplaced(None) is None
llm.set_structured_override(fake_with(RuntimeError("boom")))
assert place_page(img, [blk_a], ask)[:3] == ([], [], None)


# ── 조각 놓기 place_word (#102) ──
white = Busy(png(Image.new("RGB", (W, H), "white")))
tb = [TextBlock(paragraphs=[["가"]], x=5.0, y=7.0, color="dark")]
face = {"owner": "모아", "kind": "face", "source": (20.0, 35.0, 30.0, 50.0), "chars": [("모아", (15.0, 30.0, 35.0, 90.0))]}
sw = place_word(white, "데굴데굴", face, tb)
l, r = sw.pieces
assert [p.text for p in sw.pieces] == ["데굴", "데굴"] and (l.side, r.side) == ("left", "right"), sw
assert l.x < 20 < 30 < r.x and l.y <= 35 and r.y <= 35, sw             # 근원 양옆, 얼굴 위끝 이하 (#108 여유 뒤엔 대칭이 아닐 수 있음)
assert sw.color == "#2055B1" and sw.text == "데굴데굴" and sw.owner == "모아"
assert all(p.x == round(p.x, 1) and p.y == round(p.y, 1) for p in sw.pieces)
one = place_word(white, "엉엉", face, tb)
assert [p.side for p in one.pieces] == ["center"] and one.pieces[0].y < 30, one   # 몸 칸 위
assert [p.text for p in place_word(white, "우당탕탕", face, tb).pieces] == ["우당탕탕"]


def test_object_in_front_of_body():
    car = {"owner": "자동차", "kind": "object", "source": (55.0, 75.0, 62.0, 82.0),
           "chars": [("초코", (52.0, 35.0, 72.0, 88.0)), ("모아", (15.0, 30.0, 35.0, 90.0))]}
    got = place_word(white, "데굴데굴", car, tb)
    # 접히는 선 너머 빈 곳은 다른 캐릭터(모아)에 더 가까워 버리고, 오른쪽은 반지름 밖 → 안 띄운다. 머리 옆으로는 절대 안 간다
    assert got is None or all(p.y >= 75 - 3 for p in got.pieces), got


test_object_in_front_of_body()
held = {"owner": "자동차", "kind": "object", "source": (70.0, 70.0, 76.0, 76.0), "chars": [("초코", (62.0, 30.0, 80.0, 88.0))]}
sw = place_word(white, "데굴데굴", held, tb)
assert sw and all(abs(p.y - 73) < 6 for p in sw.pieces), sw            # 손에 든 물건도 그 높이 양옆
assert all(p.x < 62 or p.x > 80 for p in sw.pieces), sw                # 든 캐릭터 몸은 가리지 않는다
car_free = {"owner": "자동차", "kind": "object", "source": (60.0, 75.0, 66.0, 82.0), "chars": [("초코", (75.0, 35.0, 92.0, 88.0))]}
sw = place_word(white, "데굴데굴", car_free, tb)
assert sw and abs(sw.pieces[0].y - 78.5) < 3 and abs(sw.pieces[1].y - 78.5) < 3, sw   # 물건 높이 양옆


def test_edge_falls_back_to_one_piece():
    edge = {"owner": "a", "kind": "face", "source": (2.0, 30.0, 10.0, 45.0), "chars": [("a", (1.0, 28.0, 12.0, 90.0))]}
    got = place_word(white, "데굴데굴", edge, [])
    assert got is None or [p.side for p in got.pieces] == ["center"], got


test_edge_falls_back_to_one_piece()


def test_no_characters_still_places():
    got = place_word(white, "엉엉", {"owner": "a", "kind": "face", "source": (60.0, 30.0, 70.0, 45.0), "chars": []}, [])
    assert got and len(got.pieces) == 1, got


test_no_characters_still_places()
# 근원 가까움 (px 칸): 다른 캐릭터 칸이 더 가까우면 False
assert _closer_to_source((100.0, 100.0), (120.0, 90.0, 140.0, 110.0), [(50.0, 50.0, 95.0, 95.0)]) is False
assert _closer_to_source((100.0, 100.0), (105.0, 90.0, 140.0, 110.0), [(50.0, 50.0, 80.0, 80.0)]) is True
assert _closer_to_source((100.0, 100.0), (105.0, 90.0, 140.0, 110.0), []) is True
assert place_word(white, "엉엉", None, tb) is None
# 실험(11/16 샘플 동화): 한쪽이 옆 캐릭터에 막혀도 조각마다 자기 쪽에서 따로 자리를 찾는다 (거울 대칭 아님)
_ph = piece_size("데굴")[1] / H * 100
for _word, _spot in (
        ("데굴데굴", {"owner": "자동차", "kind": "object", "source": (46.0, 75.0, 53.0, 81.0),
                     "chars": [("a", (63.0, 8.0, 86.0, 83.0)), ("b", (49.0, 39.0, 68.0, 82.0))]}),
        ("사각사각", {"owner": "크레파스", "kind": "object", "source": (57.0, 67.0, 60.0, 74.0),
                     "chars": [("a", (45.0, 33.0, 66.0, 74.0)), ("b", (68.0, 11.0, 100.0, 75.0))]})):
    _got = place_word(white, _word, _spot, [])
    if _got is None or len(_got.pieces) == 1:   # #108: 인물과 여유를 두면 좁은 장면은 한 조각(또는 안 띄움)으로 내려갈 수 있다
        continue
    assert [p.side for p in _got.pieces] == ["left", "right"], (_word, _got)
    _l, _r = _got.pieces
    assert _l.x < _spot["source"][0] and _r.x > _spot["source"][2], _got                # 근원 양옆
    assert abs(_l.y - _r.y) <= 2 * _ph + 0.1, _got                                        # 높이 차이는 조각 둘 높이까지
    assert all(_spot["source"][1] - _ph - 0.1 <= p.y <= _spot["source"][3] + _ph + 0.1 for p in _got.pieces), _got   # 물건 높이 둘레
# 견줄 상대에서 빼는 캐릭터는 근원과 가장 많이 겹치는 하나뿐 (같으면 더 작은 칸 = 근원 주인)
_car = (400.0, 800.0, 460.0, 860.0)
_holder, _leg = (380.0, 350.0, 600.0, 920.0), (200.0, 300.0, 410.0, 900.0)   # 다리 칸이 자동차 끝에 살짝 겹침
assert _others("object", _car, [_holder, _leg]) == [_leg]
_face, _owner, _big = (500.0, 300.0, 560.0, 360.0), (480.0, 290.0, 600.0, 900.0), (300.0, 100.0, 900.0, 1000.0)
assert _others("face", _face, [_big, _owner]) == []                       # 얼굴을 덮는 칸은 모두 뺀다(안긴 장면: 안은 캐릭터 칸이 얼굴을 덮는다)
_side_by = (580.0, 100.0, 900.0, 1000.0)
assert _others("face", _face, [_owner, _side_by]) == [_side_by]            # 얼굴을 안 덮는 옆 캐릭터는 남는다
# 실험(11/16) 5쪽: 너구리 품에 안긴 토끼 얼굴 → 덮는 칸이 둘. 놓을 곳이 있어야 한다
hug = {"owner": "모모", "kind": "face", "source": (39.0, 23.0, 51.0, 45.0),
       "chars": [("모모", (35.0, 19.0, 52.0, 79.0)), ("라라", (37.0, 4.0, 73.0, 79.0))]}
assert place_word(white, "훌쩍훌쩍", hug, []) is not None
assert _others("face", _face, []) == [] and _others("object", _car, [_leg]) == []
# 조각은 글 덩어리·접히는 선·여백을 지킨다
fold = place_word(white, "엉엉", {"owner": "a", "kind": "face", "source": (47.0, 40.0, 53.0, 50.0), "chars": []}, [])
assert fold is None or all(abs(p.x - 50) * W / 100 >= piece_size(p.text)[0] / 2 + W * SFX_FOLD / 100 - 1 for p in fold.pieces), fold
dark = Busy(png(Image.new("RGB", (W, H), (20, 20, 30))))
assert place_word(dark, "엉엉", face, []).color == "#FFFFFF"
# 눈금: 기본(grid=True)이면 별표 있는 쪽·없는 쪽 모두 10% 눈금을 그려 보내고 지시에 알린다 (#104). grid=False면 그림 그대로
calls.clear()
llm.set_structured_override(fake_with(TextPlacementWithWord(blocks=[BlockSpot(x=6, y=8, color="dark")], characters=good_chars, sound_word=good)))
place_page(img, [blk_a], ask)
assert calls[0]["image"] != img and calls[0]["system"].count("눈금") >= 1
gi = Image.open(io.BytesIO(calls[0]["image"]))
assert gi.size == (W, H)
calls.clear()
place_page(img, [blk_a], ask, grid=False)
assert calls[0]["image"] == img and "눈금" not in calls[0]["system"]
# 눈금 그리기가 터지면 눈금 없이 원래 그림으로 묻는다 — 칸·의성어는 그대로 받는다
import firstory.nodes.layout as _lay  # noqa: E402
_orig_wg = _lay.with_grid
_lay.with_grid = lambda image: (_ for _ in ()).throw(RuntimeError("grid"))
calls.clear()
try:
    spots, wchars, wspot, _ = place_page(img, [blk_a], ask)
finally:
    _lay.with_grid = _orig_wg
assert spots == [{"x": 6.0, "y": 8.0, "color": "dark"}] and wspot is not None and len(wchars) == 2
assert calls[0]["schema"] is TextPlacementWithWord and calls[0]["image"] == img and "눈금" not in calls[0]["system"]
# 의성어 지시 준비가 터지면 의성어 없이 — 글 자리·칸은 그대로 받는다 (리뷰 #3)
_orig_pr = _lay.prompt
_lay.prompt = lambda name, **kw: (_ for _ in ()).throw(RuntimeError("p")) if name == "text_place_word" else _orig_pr(name, **kw)
calls.clear()
llm.set_structured_override(fake_with(TextPlacement(blocks=[BlockSpot(x=6, y=8, color="dark")], characters=good_chars)))
try:
    spots, wchars, wspot, _ = place_page(img, [blk_a], ask)
finally:
    _lay.prompt = _orig_pr
assert spots == [{"x": 6.0, "y": 8.0, "color": "dark"}] and wspot is None and len(wchars) == 2
assert calls[0]["schema"] is TextPlacement
llm.set_structured_override(mock.fake_structured)
assert place_page(img, [blk_a], ask)[1] != []   # mock: 의성어 쪽은 맨 위 칸
print("sound word ok")


# ── 의성어 나누기·조각 크기·색 (#102) ──
from firstory.nodes.layout import FONT_RATIO as _FR, contrast, delta_e, pick_color, piece_size, split_word  # noqa: E402

assert split_word("데굴데굴") == ["데굴", "데굴"]
assert split_word("두근두근") == ["두근", "두근"]
assert split_word("데굴 데굴") == ["데굴", "데굴"]
for _w in ("우당탕탕", "와르르르", "엉엉", "꼬르륵", "콩닥콩닥콩닥", "톡"):
    assert split_word(_w) == [_w], _w
_pw, _ph = piece_size("데굴")
assert abs(_pw - text_width("데굴") * 0.025 / _FR) < 1e-6 and abs(_ph - W * 0.025 * 1.2) < 1e-6
assert round(contrast((255, 255, 255), (0, 0, 0)), 1) == 21.0
assert delta_e((255, 255, 255), (255, 255, 255)) == 0


def _solid(rgb):
    return Busy(png(Image.new("RGB", (W, H), rgb)))


_box = [(800.0, 400.0, 100.0, 60.0)]
# #117: 진한 5색은 밝은 바탕(흰·크림·하늘)에서 모두 대비 3:1 이상, 말로 시작 색을 정해 돌려 쓴다
from firstory.nodes.layout import HUES  # noqa: E402
assert len(HUES) == 5
for _bg in ((255, 255, 255), (240, 225, 190), (170, 190, 230)):
    assert all(contrast(rgb, _bg) >= 3 for _, rgb in HUES), _bg
_words = ["쓰담쓰담", "엉엉", "콩콩", "쏙", "훌쩍훌쩍", "토닥토닥", "방긋", "톡", "냠냠", "데굴데굴"]
_white = _solid((255, 255, 255))
_picked = [pick_color(_white, _box, w) for w in _words]
assert all(c in [h for h, _ in HUES] for c in _picked), _picked
assert len(set(_picked)) >= 4, _picked                                                   # 말마다 여러 색
assert [pick_color(_white, _box, w) for w in _words] == _picked                          # 같은 말은 같은 색
assert pick_color(_solid((240, 225, 190)), _box, "쓰담쓰담") == pick_color(_white, _box, "쓰담쓰담")   # 밝은 바탕이면 바탕이 달라도
assert pick_color(_solid((32, 32, 32)), _box, "엉엉") == "#FFFFFF"                        # 어두운 바탕은 흰색
assert pick_color(_solid((140, 160, 205)), _box, "엉엉") == "#4A4A4A"                     # 진한 5색·흰색 모두 3:1 미만이면 진한 회색
assert pick_color(_white, _box * 2, "데굴데굴") == pick_color(_white, _box, "데굴데굴")    # 두 조각 = 같은 한 색
print("split color ok")


# ── 캐릭터 칸 피하기 (#104) ──
from firstory.nodes.layout import CHAR_PAD, _overlap, blockers  # noqa: E402

_wbusy = Busy(png(Image.new("RGB", (W, H), "white")))
_p = W * CHAR_PAD
assert blockers([("a", (10.0, 10.0, 20.0, 20.0))]) == [(0.1 * W - _p, 0.1 * H - _p, 0.2 * W + _p, 0.2 * H + _p)]
assert CHAR_PAD == 0.015 and blockers([]) == []
assert _overlap(0, 0, 100, 100, [(50.0, 50.0, 150.0, 150.0)]) == 2500.0
assert _overlap(0, 0, 100, 100, [(200.0, 0.0, 300.0, 100.0)]) == 0.0


def _rect(spot, block):
    bw, bh = block_size(block)
    x, y = spot["x"] / 100 * W, spot["y"] / 100 * H
    return x, y, bw, bh


# AI가 고른 자리(6%, 8%)가 캐릭터 칸 위 → 칸을 피한 곳으로 옮긴다
_av = blockers([("a", (4.0, 5.0, 30.0, 60.0))])
_got = settle(_wbusy, [blk_a], [{"x": 6, "y": 8, "color": "dark"}], _av)
assert _got and _overlap(*_rect(_got[0], blk_a), _av) == 0, _got
assert settle(_wbusy, [blk_a], [{"x": 6, "y": 8, "color": "dark"}]) == settle(_wbusy, [blk_a], [{"x": 6, "y": 8, "color": "dark"}], [])
assert settle(_wbusy, [blk_a], [{"x": 6, "y": 8, "color": "dark"}])[0]["x"] == 6.0   # 칸이 없으면 지금처럼 AI 자리 그대로
# 2덩어리: 왼쪽 면 위 띠를 칸이 덮으면 1번은 왼쪽 면 아래 띠로 (면 고정 #95 유지)
_av2 = blockers([("a", (0.0, 0.0, 50.0, 45.0))])
_got2 = settle(_wbusy, [blk_a, blk_b], [{"x": 6, "y": 8, "color": "dark"}, {"x": 55, "y": 8, "color": "dark"}], _av2)
assert _got2 and _got2[0]["x"] < 50 and _got2[0]["y"] > 50 and _got2[1]["x"] >= 50, _got2
assert all(_overlap(*_rect(s, b), _av2) == 0 for s, b in zip(_got2, [blk_a, blk_b])), _got2
# 어디에도 칸을 피할 곳이 없으면 None (호출한 쪽이 다음 단계로)
assert settle(_wbusy, [blk_a], [{"x": 6, "y": 8, "color": "dark"}], blockers([("a", (0.0, 0.0, 100.0, 100.0))])) is None
print("avoid ok")


# ── 한 덩어리를 둘로 나누기 split_block (#104) ──
from firstory.nodes.layout import split_block  # noqa: E402

assert split_block([["a.", "b."], ["c.", "d."]]) == [[["a.", "b."]], [["c.", "d."]]]
assert split_block([["a.", "b.", "c.", "d."]]) == [[["a.", "b."]], [["c.", "d."]]]
assert split_block([["a.", "b.", "c."]]) == [[["a.", "b."]], [["c."]]]                     # 같으면 뒤쪽 경계
# 문단이 쏠리면(큰 쪽이 2/3 초과) 줄 경계에서 가운데로: 본문 6줄 + 질문 1줄
assert split_block([["1.", "2.", "3.", "4.", "5.", "6."], ["질문?"]]) == [[["1.", "2.", "3.", "4."]], [["5.", "6."], ["질문?"]]]
# 쏠리지 않으면 문단 경계: 4줄 + 3줄
assert split_block([["1.", "2.", "3.", "4."], ["5.", "6.", "7."]]) == [[["1.", "2.", "3.", "4."]], [["5.", "6.", "7."]]]
# 대사(따옴표가 열린 채)에서는 나누지 않는다
assert split_block([['"가나다', '라마바."']]) is None
assert split_block([['가.', '"나다', '라마."']]) == [[['가.']], [['"나다', '라마."']]]
assert split_block([["한 줄."]]) is None and split_block([]) is None
for _b in ([["1.", "2.", "3.", "4.", "5.", "6."], ["질문?"]], [["a.", "b.", "c."]], [['가.', '"나다', '라마."']]):
    _o = split_block(_b)
    assert [l for blk in _o for para in blk for l in para] == [l for para in _b for l in para]   # 줄 순서·글자 그대로
# 리뷰: 감긴 한 문장은 문장 중간(감긴 줄 사이)에서 양쪽 면으로 나누지 않는다
assert split_block([["미루는 블록을 아주 높이 높이", "쌓아 올리고 친구에게 보여 주며", "활짝 웃었어요."]]) is None
assert split_block([["가온이 왔어요.", "미루는 블록을 아주 높이", "쌓았어요."]]) == [[["가온이 왔어요."]], [["미루는 블록을 아주 높이", "쌓았어요."]]]
assert split_block([["1.", "2.", "3.", "4.", "5.", "6."], ["가온 마음은 어떻게", "달라졌을까요?"]]) == [[["1.", "2.", "3.", "4."]], [["5.", "6."], ["가온 마음은 어떻게", "달라졌을까요?"]]]
assert split_block([['미루가 말했어요.', '"같이 다시 쌓을래?"', '가온이 끄덕였어요!']]) == [[['미루가 말했어요.', '"같이 다시 쌓을래?"']], [['가온이 끄덕였어요!']]]
print("split block ok")


# ── 마지막 안전판: 겹침 먼저 (#104) ──
_b7 = [[f"미루가 블록을 {i}번 쌓았어요." for i in range(1, 8)]]
_av7 = blockers([("a", (0.0, 45.0, 50.0, 100.0)), ("b", (50.0, 50.0, 100.0, 100.0))])


def _over(blocks, spots, avoid):
    return sum(_overlap(*_rect(s, b), avoid) for b, s in zip(blocks, spots))


assert settle(_wbusy, [_b7], [{"x": 6, "y": 8, "color": "dark"}], _av7) is None          # 7줄 한 덩어리는 어디에 둬도 칸에 닿는다
_bl, _sp = calmest_pick(_wbusy, [_b7], _av7)
assert len(_bl) == 2 and _over(_bl, _sp, _av7) == 0, (_bl, _sp)                         # 나눈 두 덩어리가 뽑힘
assert _sp[0]["x"] < 50 <= _sp[1]["x"]
# 그림 전체가 칸이어도 늘 자리는 있고, 겹침은 칸을 모를 때보다 작거나 같다
_avall = blockers([("a", (0.0, 20.0, 100.0, 100.0))])
_bl, _sp = calmest_pick(_wbusy, [blk_a], _avall)
_bl0, _sp0 = calmest_pick(_wbusy, [blk_a])
assert _over(_bl, _sp, _avall) <= _over(_bl0, _sp0, _avall), (_sp, _sp0)
assert calmest(_wbusy, [blk_a], _avall) is not None
print("calmest avoid ok")


# ── 겹침은 줄마다 실제 글자 폭으로 잰다 (4쪽: 긴 첫 줄 때문에 네모가 칸에 닿아 벽 자리를 버렸음) ──
from firstory.nodes.layout import LINE_PX  # noqa: E402

_long = "초코가 모아 옆의 바퀴 블록으로 손을"
_blk = [[_long, "뻗었어요."], ["음."]]
_wl = text_width(_long) / W * 100
_x0 = 5 + text_width("뻗었어요.") / W * 100 + 1.5 + 3              # 짧은 줄 오른쪽 끝 + 여백 + 3%
_y0 = 7 + LINE_PX / H * 100 + 1.5 * W / H + 1                       # 첫 줄 아래 + 여백 + 1%
assert _x0 < 5 + _wl                                                 # 덩어리 네모는 칸에 닿는다
_avr = blockers([("a", (_x0, _y0, 60.0, 95.0))])
_got = settle(_wbusy, [_blk], [{"x": 5, "y": 7, "color": "dark"}], _avr)
assert _got == [{"x": 5.0, "y": 7.0, "color": "dark"}], _got          # 실제 글자는 안 닿으니 AI 자리 그대로
print("row overlap ok")


# ── 마지막 안전판: 캐릭터 몸에는 안 닿고 여백만 살짝 걸치는 조용한 벽 > 겹침 0인 복잡한 물건 위 ──
def _busy_but_topleft() -> Busy:
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    for x in range(0, W, 24):
        d.rectangle([x, 0, x + 11, H], fill=(40, 40, 40))
    d.rectangle([0, 0, W // 2, int(H * 0.45)], fill="white")        # 왼쪽 위만 조용한 벽
    return Busy(png(im))


_one = [["모아는 울고 싶었어요."]]
_w1 = text_width("모아는 울고 싶었어요.") / W * 100
# 칸 왼쪽 끝을 글 오른쪽 끝 + 0.5%에: 캐릭터 몸에는 안 닿고 넉넉히 키운 여백(1.5%)에만 걸친다. 칸은 위쪽만이라 아래 띠는 겹침 0
_xa = 5 + _w1 + 0.5
_avm = blockers([("a", (_xa, 0.0, 100.0, 60.0))])
_bbusy = _busy_but_topleft()
assert settle(_bbusy, [_one], [{"x": 5, "y": 7, "color": "dark"}], _avm) is None   # 엄격한 자리는 없다
_bl, _sp = calmest_pick(_bbusy, [_one], _avm)
assert _sp[0]["x"] < 50 and _sp[0]["y"] < 45, _sp                                     # 조용한 왼쪽 위 벽
print("fallback prefers calm wall ok")


# ── 의성어 조각은 캐릭터 칸에서 여유(CHAR_PAD)를 두고 떨어진다 (#108: 96번 4쪽 '훌쩍훌쩍'이 귀 끝에 닿음) ──
def _clear_of(sw, chars):
    """모든 조각이 CHAR_PAD만큼 키운 캐릭터 칸(%)과 안 겹치나"""
    for q in (sw.pieces if sw else []):
        qw, qh = piece_size(q.text)
        r = (q.x / 100 * W - qw / 2, q.y / 100 * H - qh / 2, q.x / 100 * W + qw / 2, q.y / 100 * H + qh / 2)
        for c in chars:
            cp = (c[0] / 100 * W - W * CHAR_PAD, c[1] / 100 * H - W * CHAR_PAD, c[2] / 100 * W + W * CHAR_PAD, c[3] / 100 * H + W * CHAR_PAD)
            if r[0] < cp[2] and cp[0] < r[2] and r[1] < cp[3] and cp[1] < r[3]:
                return False
    return True


_scenes = [
    ("훌쩍훌쩍", {"owner": "나리", "kind": "face", "source": (37.0, 38.0, 46.0, 55.0),
                 "chars": [("나리", (35.0, 33.0, 48.0, 85.0)), ("솔", (49.0, 37.0, 63.0, 86.0))]}),
    ("데굴데굴", face), ("엉엉", face), ("데굴데굴", held), ("데굴데굴", car_free), ("훌쩍훌쩍", hug),
    ("데굴데굴", {"owner": "자동차", "kind": "object", "source": (46.0, 75.0, 53.0, 81.0),
                 "chars": [("a", (63.0, 8.0, 86.0, 83.0)), ("b", (49.0, 39.0, 68.0, 82.0))]}),
    ("사각사각", {"owner": "크레파스", "kind": "object", "source": (57.0, 67.0, 60.0, 74.0),
                 "chars": [("a", (45.0, 33.0, 66.0, 74.0)), ("b", (68.0, 11.0, 100.0, 75.0))]}),
]
for _w, _s in _scenes:
    _sw = place_word(_wbusy, _w, _s, [])
    assert _clear_of(_sw, [b for _, b in _s["chars"]]), (_w, _s, _sw)
print("sound word pad ok")


# ── 손 동작(쓰담쓰담·토닥토닥·콩콩 맞대기)은 손이 닿는 곳이 근원 (#119) ──
# 11/17 샘플 4쪽: AI가 쓰다듬는 쪽 얼굴(face)로 답해 어른 얼굴 위끝 = 그림 맨 위(8~10%)로 갔다.
# 손은 두 몸 칸 사이에 묻혀 지금 반지름(15%)으로는 자리가 없다 → touch: 한 조각, 손 칸에서 몸 칸 밖 가장 가까운 곳(반지름 25%), 없으면 None
from firstory.nodes.layout import _rect_dist  # noqa: E402

assert WordSpot(owner="손", source_kind="touch", source_box=ob(41, 60, 62, 73)).source_kind == "touch"
_t = wplaced(WordSpot(owner="손", source_kind="touch", source_box=ob(41, 60, 62, 73)))
assert _t and _t["kind"] == "touch" and _t["source"] == (41.0, 60.0, 62.0, 73.0), _t
_pw = prompt("text_place_word", word="쓰담쓰담", text="엄마가 미로를 **쓰담쓰담** 했어요.", cast="- (없음)")
assert "touch" in _pw and "쓰담쓰담" in _pw and "손" in _pw
llm.set_structured_override(mock.fake_structured)
# 견줄 상대: 손과 겹치는 캐릭터(쓰다듬는 쪽·받는 쪽)는 모두 뺀다
_hand = (800.0, 650.0, 1000.0, 750.0)
assert _others("touch", _hand, [(700.0, 300.0, 1250.0, 1000.0), (900.0, 100.0, 1700.0, 1000.0), (100.0, 100.0, 400.0, 900.0)]) == [(100.0, 100.0, 400.0, 900.0)]
assert _lay.SFX_TOUCH_RADIUS == 0.25
_touch_scenes = [   # (말, 손 칸, 캐릭터 칸) — 캐릭터 칸은 11/17 진짜 답, 손 칸은 그림을 보고 잡음 (out/sound-word-top-1117)
    ("쓰담쓰담", (41.0, 60.0, 62.0, 73.0), [("하람", (51.0, 10.0, 90.0, 95.0)), ("미루", (38.0, 35.0, 63.0, 80.0))]),
    ("쓰담쓰담", (54.0, 49.0, 60.0, 57.0), [("나루", (39.0, 31.0, 61.0, 83.0)), ("미소", (60.0, 10.0, 92.0, 92.0))]),
    ("쓰담쓰담", (57.0, 39.0, 65.0, 47.0), [("엄마 토끼", (57.0, 14.0, 91.0, 92.0)), ("미로", (47.0, 37.0, 65.0, 92.0))]),
    ("콩콩", (67.0, 58.0, 73.0, 67.0), [("모아", (70.0, 6.0, 93.0, 96.0)), ("코알라", (48.0, 47.0, 76.0, 92.0)), ("엄마", (69.0, 8.0, 92.0, 93.0))]),
]
for _w, _src, _chars in _touch_scenes:
    _sw = place_word(white, _w, {"owner": "손", "kind": "touch", "source": _src, "chars": _chars}, [])
    assert _sw and [(p.text, p.side) for p in _sw.pieces] == [(_w, "center")], (_w, _sw)   # 반복 말도 한 조각
    _p = _sw.pieces[0]
    assert _p.y >= 20, (_w, _sw)                                                        # 그림 맨 위로 안 간다
    _pw_, _ph_ = piece_size(_w)
    _d = _rect_dist((_p.x / 100 * W, _p.y / 100 * H), tuple(v / 100 * (W if i % 2 == 0 else H) for i, v in enumerate(_src)))
    assert _d <= W * _lay.SFX_TOUCH_RADIUS, (_w, _d)                                          # 손에서 반지름 안
    assert _clear_of(_sw, [b for _, b in _chars]), (_w, _sw)                             # 몸은 가리지 않는다
# 손 둘레가 모두 몸이면 안 띄운다
_crowd = [("a", (5.0, 5.0, 48.0, 95.0)), ("b", (52.0, 5.0, 95.0, 95.0))]
assert place_word(white, "토닥토닥", {"owner": "손", "kind": "touch", "source": (40.0, 40.0, 45.0, 45.0), "chars": _crowd}, []) is None
print("sound word touch ok")
