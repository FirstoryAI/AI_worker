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
from firstory.schemas import BlockSpot, TextChunking, TextPlacement  # noqa: E402

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
spots, _, costs = place_page(img, [blk_a, blk_b])
assert spots == [{"x": 6.0, "y": 8.0, "color": "dark"}, {"x": 55.5, "y": 70.0, "color": "light"}], spots
assert [c.node for c in costs] == ["layout:place"]
assert calls[0]["schema"] is TextPlacement and calls[0]["image"] == img and "{{" not in calls[0]["system"]
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
assert place_page(img, [blk_a]) == ([], None, [])                                                          # 예외 → []
llm.set_structured_override(fake_with(lambda kw: type("Bad", (), {"blocks": [type("S", (), {"x": "abc", "y": None, "color": "dark"})()]})()))
assert place_page(img, [blk_a])[0] == []                                                             # 숫자 아님
assert place_page(img, []) == ([], None, [])                                                               # 덩어리 없으면 부르지 않음

# mock 모드 배선: 진짜 fake_structured 가 두 스키마를 모두 답한다
llm.set_structured_override(mock.fake_structured)
ls, cks, _ = chunk_page(text)
assert cks == [[ls]], cks
assert place_page(img, [blk_a, blk_b])[0] == [{"x": 5.0, "y": 7.0, "color": "dark"}] * 2
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
    SFX_FOLD, SfxAsk, settle_word, short_look, sound_words, word_size,
)
from firstory.schemas import OwnerBox, SoundWord, TextPlacementWithWord, WordSpot  # noqa: E402

assert sound_words("미루가 **훌쩍훌쩍** 울었어요.") == ["훌쩍훌쩍"]
assert sound_words("**톡** 치고 ** 냠냠 **") == ["톡", "냠냠"]
assert sound_words("별표 없음.") == []
assert short_look("A small white rabbit with long ears. Wears a yellow apron.") == "A small white rabbit with long ears"
assert len(short_look("x" * 300)) == 120
ww, wh = word_size("훌쩍")
assert abs(ww - text_width("훌쩍") * 0.035 / FONT_RATIO) < 1e-6 and abs(wh - W * 0.035 * 1.2) < 1e-6

# place_page: 별표 없는 쪽은 지금 호출 그대로
calls.clear()
llm.set_structured_override(fake_with(TextPlacement(blocks=[BlockSpot(x=6, y=8, color="dark")])))
spots, wspot, costs = place_page(img, [blk_a])
assert wspot is None and calls[0]["schema"] is TextPlacement and "의성어" not in calls[0]["system"]
sys0, user0 = calls[0]["system"], calls[0]["user"]

# 별표 있는 쪽: 의성어 단락 + 의성어 스키마
ask = SfxAsk(word="훌쩍훌쩍", text="미루가 **훌쩍훌쩍** 울었어요.", cast=[("미루", "A small white rabbit")])
calls.clear()
llm.set_structured_override(fake_with(TextPlacementWithWord(blocks=[BlockSpot(x=6, y=8, color="dark")],
                                                            sound_word=WordSpot(owner="미루", owner_box=OwnerBox(x0=50, y0=30, x1=60, y1=80), x=62.5, y=31))))
spots, wspot, costs = place_page(img, [blk_a], ask)
assert spots == [{"x": 6.0, "y": 8.0, "color": "dark"}] and [c.node for c in costs] == ["layout:place"]
assert wspot == {"x": 62.5, "y": 31.0, "owner": "미루", "box": (50.0, 30.0, 60.0, 80.0)}, wspot
assert calls[0]["schema"] is TextPlacementWithWord
assert all(s in calls[0]["system"] for s in ("훌쩍훌쩍", "미루", "A small white rabbit")) and "{{" not in calls[0]["system"]
assert calls[0]["system"].startswith(sys0) and calls[0]["user"].startswith(user0)   # 지금 지시 뒤에 붙일 뿐


def wplaced(x, y, box=None):
    llm.set_structured_override(fake_with(TextPlacementWithWord.model_construct(
        blocks=[BlockSpot(x=6, y=8, color="dark")], sound_word=WordSpot.model_construct(owner="미루", x=x, y=y, owner_box=box))))
    return place_page(img, [blk_a], ask)[1]


assert wplaced(1200, 300) == {"x": 1200 / W * 100, "y": 300 / H * 100, "owner": "미루", "box": None}   # 픽셀 → %, 칸 없음
assert wplaced(62, 31, OwnerBox.model_construct(x0=960, y0=30, x1=60, y1=80))["box"] is None          # 칸이 뒤집힘 → 칸 없음
assert wplaced(62, 31, OwnerBox.model_construct(x0=50, y0=float("nan"), x1=60, y1=80))["box"] is None
assert wplaced(62, 31, OwnerBox.model_construct(x0=50, y0=30, x1=60, y1=180))["box"] is None          # 0~100 밖 → 칸 없음
assert wplaced(float("nan"), 30) is None and wplaced(-5, 30) is None and wplaced("a", 30) is None
llm.set_structured_override(fake_with(RuntimeError("boom")))
assert place_page(img, [blk_a], ask)[:2] == ([], None)


def word_box(sw):
    w, h = word_size(sw.text)
    cx, cy = sw.x / 100 * W, sw.y / 100 * H
    return cx - w / 2, cy - h / 2, w, h


def word_box_gap_ok(sw, tbs):
    x, y, w, h = word_box(sw)
    g = W * GAP
    for b in tbs:
        bw, bh = block_size(b.paragraphs)
        px, py = b.x / 100 * W, b.y / 100 * H
        if not (x + w + g <= px + 1 or px + bw + g <= x + 1 or y + h + g <= py + 1 or py + bh + g <= y + 1):
            return False
    return True


white = Busy(png(Image.new("RGB", (W, H), "white")))
tb = [TextBlock(paragraphs=blk_a, x=5.0, y=7.0, color="dark")]
ok = settle_word(white, "훌쩍훌쩍", {"x": 75.0, "y": 40.0, "owner": "미루"}, tb)
assert ok == SoundWord(text="훌쩍훌쩍", x=75.0, y=40.0, color="dark", owner="미루"), ok   # 조건을 지키면 그대로
# 덩어리 위에 놓인 말은 밀려나 2% 이상 떨어진다
on_block = settle_word(white, "훌쩍훌쩍", {"x": 10.0, "y": 9.0, "owner": "미루"}, tb)
assert on_block is not None and word_box_gap_ok(on_block, tb), on_block
assert on_block.x == round(on_block.x, 1) and on_block.y == round(on_block.y, 1)
# 접히는 선 위의 말은 선에서 2% 이상
on_fold = settle_word(white, "훌쩍훌쩍", {"x": 50.0, "y": 40.0, "owner": "미루"}, [])
fx, _, fw, _ = word_box(on_fold)
assert fx + fw <= W * (0.5 - SFX_FOLD / 100) + 1 or fx >= W * (0.5 + SFX_FOLD / 100) - 1, on_fold
# 가장자리: 그림 밖으로 나간 말은 여백 안으로
edge = settle_word(white, "훌쩍훌쩍", {"x": 99.0, "y": 99.0, "owner": "미루"}, [])
ex, ey, ew_, eh_ = word_box(edge)
assert ex + ew_ <= W * 0.97 + 1 and ey + eh_ <= H * 0.96 + 1, edge
# 반지름 15% 안이 모두 덩어리면 None
wall = [TextBlock(paragraphs=[["가" * 30]] * 14, x=5.0, y=7.0, color="dark")]
assert settle_word(white, "훌쩍훌쩍", {"x": 20.0, "y": 40.0, "owner": "미루"}, wall) is None
assert settle_word(white, "훌쩍훌쩍", None, tb) is None
# 주인 칸: 말이 주인 칸에 겹치면 칸 바깥으로 밀려 2% 이상 떨어진다
on_owner = settle_word(white, "훌쩍훌쩍", {"x": 70.0, "y": 50.0, "owner": "미루", "box": (60.0, 30.0, 80.0, 80.0)}, tb)
assert on_owner is not None, on_owner
ox, oy, ow_, oh_ = word_box(on_owner)
g = W * GAP
bx0, by0, bx1, by1 = 0.60 * W, 0.30 * H, 0.80 * W, 0.80 * H
assert ox + ow_ + g <= bx0 + 1 or bx1 + g <= ox + 1 or oy + oh_ + g <= by0 + 1 or by1 + g <= oy + 1, on_owner
# 주인 칸 바깥이면 그대로
off_owner = settle_word(white, "훌쩍훌쩍", {"x": 70.0, "y": 20.0, "owner": "미루", "box": (60.0, 30.0, 80.0, 80.0)}, tb)
assert (off_owner.x, off_owner.y) == (70.0, 20.0), off_owner
# 어두운 바탕 → light
dark = Busy(png(Image.new("RGB", (W, H), (20, 20, 30))))
assert settle_word(dark, "훌쩍", {"x": 75.0, "y": 40.0, "owner": "미루"}, []).color == "light"
# 눈금: grid=True면 의성어 쪽 그림에 10% 눈금을 그려 보내고 지시에 알린다. 별표 없는 쪽은 그림 그대로
calls.clear()
llm.set_structured_override(fake_with(TextPlacementWithWord(blocks=[BlockSpot(x=6, y=8, color="dark")],
                                                            sound_word=WordSpot(owner="미루", owner_box=OwnerBox(x0=50, y0=30, x1=60, y1=80), x=62.5, y=31))))
place_page(img, [blk_a], ask, grid=True)
assert calls[0]["image"] != img and "눈금" in calls[0]["system"]
gi = Image.open(io.BytesIO(calls[0]["image"]))
assert gi.size == (W, H)
calls.clear()
place_page(img, [blk_a], ask)
assert calls[0]["image"] == img and "눈금" not in calls[0]["system"]
calls.clear()
llm.set_structured_override(fake_with(TextPlacement(blocks=[BlockSpot(x=6, y=8, color="dark")])))
place_page(img, [blk_a], None, grid=True)
assert calls[0]["image"] == img and calls[0]["system"] == sys0
# 의성어 준비(크기 재기·지시·눈금)가 터지면 의성어 없이 예전 호출로 — 글 자리는 그대로 받는다 (리뷰 #3)
import firstory.nodes.layout as _lay  # noqa: E402
_orig_ws = _lay.word_size
_lay.word_size = lambda w: (_ for _ in ()).throw(RuntimeError("font"))
calls.clear()
llm.set_structured_override(fake_with(TextPlacement(blocks=[BlockSpot(x=6, y=8, color="dark")])))
try:
    spots, wspot, _ = place_page(img, [blk_a], ask, grid=True)
finally:
    _lay.word_size = _orig_ws
assert spots == [{"x": 6.0, "y": 8.0, "color": "dark"}] and wspot is None
assert calls[0]["schema"] is TextPlacement and calls[0]["system"] == sys0 and calls[0]["image"] == img
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
assert pick_color(_solid((255, 255, 255)), _box) == "#7B4FD6"
assert pick_color(_solid((32, 32, 32)), _box) == "#F0661E"
assert pick_color(_solid((240, 225, 190)), _box) == "#7B4FD6"
assert pick_color(_solid((170, 190, 230)), _box) == "#4A4A4A"
assert pick_color(_solid((255, 255, 255)), _box * 2) == "#7B4FD6"   # 두 조각 = 같은 한 색
print("split color ok")
