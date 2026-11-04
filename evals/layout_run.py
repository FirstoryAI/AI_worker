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
    Busy, block_size, build_blocks, chunk_page, merge, normalize_chunks, place_page, settle, split_lines, text_width, wrap_line,
)
from firstory import llm, mock  # noqa: E402
from firstory.schemas import BlockSpot, TextChunking, TextPlacement  # noqa: E402

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
llm.set_structured_override(fake_with(TextChunking(blocks=[[[0], [1]], [[2], [3]]])))
ql, cks, _ = chunk_page(q)
assert cks == [[[ql[0]], [ql[1], ql[2]], [ql[3]]]] or cks == [[[ql[0]], [ql[1], ql[2]]], [[ql[3]]]], cks
assert [l for c in cks for p in c for l in p] == ql
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
spots, costs = place_page(img, [blk_a, blk_b])
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
assert place_page(img, [blk_a]) == ([], [])                                                          # 예외 → []
llm.set_structured_override(fake_with(lambda kw: type("Bad", (), {"blocks": [type("S", (), {"x": "abc", "y": None, "color": "dark"})()]})()))
assert place_page(img, [blk_a])[0] == []                                                             # 숫자 아님
assert place_page(img, []) == ([], [])                                                               # 덩어리 없으면 부르지 않음

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
