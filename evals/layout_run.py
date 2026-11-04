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
    BAND, BUSY_LIMIT, EDGE_X, EDGE_Y, FOLD, GAP, H, MAX_LINE, W,
    Busy, block_size, build_blocks, merge, normalize_chunks, settle, split_lines, text_width, wrap_line,
)

# ── 줄 나누기 ──
assert split_lines('라라가 골랐어요. "어제 그 말 들으니 속상했어. 나는 같이 그리고 싶었어."') == [
    '라라가 골랐어요.', '"어제 그 말 들으니 속상했어.', '나는 같이 그리고 싶었어."']
assert split_lines('"알겠어…" 미나가 말했어요.') == ['"알겠어…" 미나가 말했어요.']
assert split_lines("하루가 **토닥토닥** 했어요.\n잘 자.") == ["하루가 **토닥토닥** 했어요.", "잘 자."]
assert split_lines("그래...  좋아.") == ["그래...  좋아."]                      # 말줄임표는 끊지 않음
long = '"어제는 내 그림을 혼자 끝내고 싶었어. 라라가 싫어서 간 건 아니야."'
wrapped = wrap_line(long)
assert len(wrapped) >= 2 and " ".join(wrapped) == long
assert all(text_width(l) <= W * MAX_LINE for l in wrapped)
assert wrap_line("짧은 줄.") == ["짧은 줄."]
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

w, h = block_size([["가나다"], ["라마"]]); assert h == (2 + 0.6) * 29 * 1.55
assert abs(w - text_width("가나다")) < 1e-9
assert block_size([["가", "나", "다"]])[1] == 3 * 29 * 1.55


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
assert out and out[0]["color"] == "light"
check_one(out[0], bw, bh)
assert out[0]["y"] != 45

# 2-1) 이미 괜찮은 자리는 그대로 둔다
out = settle(busy, [blk], [{"x": 55, "y": 8, "color": "dark"}])
assert out == [{"x": 55.0, "y": 8.0, "color": "dark"}], out

# 2-2) 여백 밖으로 붙은 자리는 면 안으로 민다 (오른쪽 가장자리에 붙임 → 안쪽으로)
out = settle(busy, [blk], [{"x": 80, "y": 8, "color": "dark"}])
assert out and out[0]["x"] / 100 * W + bw <= W * (1 - EDGE_X / 100) + 1, out
check_one(out[0], bw, bh)

# 3) 덩어리 2개: 1 이 오른쪽 면 위, 2 가 왼쪽 면 → 읽는 순서를 지키는 자리로 옮김
blk2 = [["넷째 줄이에요.", "다섯째 줄이에요."]]
bw2, bh2 = block_size(blk2)
s1 = {"x": 55, "y": 8, "color": "dark"}
out = settle(busy, [blk, blk2], [s1, {"x": 8, "y": 70, "color": "light"}])
assert out and len(out) == 2 and out[0] == {"x": 55.0, "y": 8.0, "color": "dark"}, out
check_one(out[1], bw2, bh2)
assert (page(out[1], bw2), out[1]["y"]) > (page(out[0], bw), out[0]["y"]), out       # 오른쪽 면, 1 보다 아래
assert out[1]["color"] == "light"

# 3-1) 순서를 지키는 두 자리(왼쪽 면 위 → 오른쪽 면 아래)는 그대로 둔다
out = settle(busy, [blk, blk2], [{"x": 8, "y": 70, "color": "dark"}, {"x": 55, "y": 75, "color": "light"}])
assert out == [{"x": 8.0, "y": 70.0, "color": "dark"}, {"x": 55.0, "y": 75.0, "color": "light"}], out
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
assert (page(out[0], bw), out[0]["y"]) < (page(out[1], bw2), out[1]["y"])

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

print("layout ok")
