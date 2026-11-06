"""
쪽 글 배치 계산 (API 없음): 줄 나누기 → 덩어리 정리 → 크기 → 자리(여백·띠·복잡도·읽는 순서).
설계: docs/superpowers/specs/2026-11-04-text-blocks-design.md 2·3·5절.
"""
from __future__ import annotations

import io
import logging
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageFont

from ..config import config
from ..llm import prompt, structured, structured_image
from ..schemas import CostEntry, TextChunking, TextPlacement

log = logging.getLogger("firstory.layout")

W, H = 1920, 1088                  # 그림 기준 크기(px)
FONT_RATIO = 0.015                 # 글자 크기 = 그림 폭의 1.5%
LINE_H = 1.55                      # 줄 높이 = 글자 크기 배수
PARA_GAP = 0.6                     # 문단 사이 = 줄 수
MAX_LINE = 0.38                    # 한 줄 최대 폭 = 그림 폭의 38%
EDGE_Y, EDGE_X, FOLD, BAND = 7, 5, 4, 20   # 위·아래 여백, 좌우 여백, 접히는 선 여백, 띠 (모두 %)
BUSY_LIMIT = 8.0                   # 복잡도(RGB 표준편차) 통과 기준
BUSY_PAD = 0.03                    # 복잡도를 재는 둘레 (그림 폭 대비)
GAP = 0.02                         # 덩어리 사이 최소 간격 (그림 폭 대비)
MAX_REDRAWS = 2                    # 한 번 실행에서 다시 그리는 쪽 상한
DEFAULT_SPOT = (5.0, 7.0, "dark")  # 마지막 안전판: 왼쪽 면 위 (그림을 못 읽거나 놓을 곳이 아예 없을 때만)
DARK_TEXT = (0x4A, 0x4A, 0x4A)     # 화면의 진한 글자색 (프론트 StoryTextBlocks)
WHITE_BIAS = 0.9                   # 흰 글자 대비가 진한 글자 대비의 이 배 이상이면 흰 글자 (비슷하면 흰 글자가 더 잘 읽힌다)

FONT_PX = round(W * FONT_RATIO)    # 29
LINE_PX = FONT_PX * LINE_H
FONT_PATH = Path(__file__).parents[1] / "assets/fonts/MemomentKkukkukk.woff2"
GRID = 8                           # 자리 찾기 격자(px)
MOVE_COST = 0.01                   # 원래 자리와 멀어진 만큼 더하는 점수(px당)
TIE_COST = 1e-5                    # calmest: 거리는 복잡도가 같을 때만 가르는 정도

Block = list[list[str]]            # 덩어리 = 문단 > 줄

_SENTENCE_END = re.compile(r'(?<!\.)\.(?!\.)["”’]?\s+')   # 마침표(말줄임표 제외) 뒤에서 자름
_DQUOTES = '"“”'


# ── 줄 ──
def _quote_open(s: str) -> bool:
    """s 끝에서 큰따옴표가 열려 있나 (따옴표 개수가 홀수)."""
    return sum(s.count(q) for q in _DQUOTES) % 2 == 1


def split_lines(text: str) -> list[str]:
    """원래 줄바꿈과 마침표마다 줄을 나눈다. 글자는 그대로.
    대사 하나는 한 줄이다 (#77): 따옴표 안의 마침표·줄바꿈에서는 자르지 않는다. 화면 폭을 넘으면 wrap_line이 자른다."""
    raws: list[str] = []
    for raw in text.split("\n"):
        raw = raw.strip()
        if raws and _quote_open(raws[-1]):   # 앞 줄에서 열린 대사가 이 줄로 이어진다
            raws[-1] = f"{raws[-1]} {raw}".strip()
        else:
            raws.append(raw)
    out: list[str] = []
    for raw in raws:
        pos = 0
        for m in _SENTENCE_END.finditer(raw):
            if _quote_open(raw[:m.end()]):       # 대사 안의 마침표
                continue
            out.append(raw[pos:m.end()].strip())
            pos = m.end()
        if raw[pos:]:
            out.append(raw[pos:].strip())
    return [line for line in out if line]


@lru_cache(maxsize=1)
def _font() -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), FONT_PX, layout_engine=ImageFont.Layout.BASIC)   # Raqm이 있는 맥과 없는 리눅스가 같은 폭을 재도록


def text_width(line: str) -> float:
    """1920 폭 기준 px. 강조 표시(**)는 빼고 잰다."""
    return _font().getlength(line.replace("**", ""))


def wrap_line(line: str) -> list[str]:
    """한 줄이 38%를 넘으면 띄어쓰기에서 자른다."""
    limit = W * MAX_LINE
    if text_width(line) <= limit:
        return [line]
    out: list[str] = []
    cur = ""
    emph = False                          # cur 끝에서 **강조**가 열려 있는지
    for word in line.split(" "):
        trial = f"{cur} {word}" if cur else word
        if cur and text_width(trial) > limit:
            out.append(cur + "**" if emph else cur)     # 강조 안에서 자르면 줄마다 표시를 닫고 다시 연다
            cur = ("**" if emph else "") + word
        else:
            cur = trial
        emph ^= word.count("**") % 2 == 1
    out.append(cur)
    return out


# ── 덩어리 ──
def _valid_idx(n: int, idx) -> bool:
    if not isinstance(idx, list) or not 1 <= len(idx) <= 2:
        return False
    flat: list = []
    for chunk in idx:
        if not isinstance(chunk, list) or not chunk:
            return False
        for para in chunk:
            if not isinstance(para, list) or not para:
                return False
            flat.extend(para)
    return all(type(i) is int for i in flat) and flat == list(range(n))


def normalize_chunks(n_lines: int, idx: list[list[list[int]]], lines: list[str] | None = None) -> list[list[list[int]]]:
    """줄 번호 나누기를 확인한다: 모든 줄을 순서대로 한 번씩, 덩어리 1~2개. 아니면 한 덩어리 한 문단.
    lines 를 주면 따옴표가 열린 줄부터 닫히는 줄까지의 문단·덩어리 끊김을 붙인다."""
    if not _valid_idx(n_lines, idx):
        return [[list(range(n_lines))]]
    # 줄마다 (덩어리, 문단) 이름표
    label = [(ci, pi) for ci, chunk in enumerate(idx) for pi, para in enumerate(chunk) for _ in para]
    if lines is not None and len(lines) == n_lines:
        open_quote = False
        for i in range(n_lines - 1):
            if sum(lines[i].count(q) for q in _DQUOTES) % 2:
                open_quote = not open_quote
            if open_quote:                       # i 줄 끝에서 따옴표가 열려 있음 → 다음 줄을 같은 문단에
                label[i + 1] = label[i]
    out: list[list[list[int]]] = []
    prev: tuple[int, int] | None = None
    for i, lab in enumerate(label):
        if prev is None or lab[0] != prev[0]:
            out.append([[i]])
        elif lab[1] != prev[1]:
            out[-1].append([i])
        else:
            out[-1][-1].append(i)
        prev = lab
    return out


def build_blocks(lines: list[str], idx: list[list[list[int]]]) -> list[Block]:
    """덩어리 > 문단 > 줄. 38%를 넘는 줄은 띄어쓰기에서 한 번 더 자른다."""
    return [[[w for i in para for w in wrap_line(lines[i])] for para in chunk] for chunk in idx]


def merge(blocks: list[Block]) -> list[Block]:
    """한 덩어리로 합친다. 문단은 그대로."""
    return [[para for block in blocks for para in block]]


def block_size(block: Block) -> tuple[float, float]:
    """(폭 px, 높이 px), 1920×1088 기준."""
    rows = [line for para in block for line in para]
    n = len(rows)
    width = max((text_width(l) for l in rows), default=0.0)
    return width, (n + PARA_GAP * (len(block) - 1)) * FONT_PX * LINE_H


# ── 복잡도 ──
class Busy:
    """그림의 영역별 복잡도(RGB 표준편차 평균). 1/4로 줄여 적분 영상으로 잰다."""

    S = 4

    def __init__(self, image: bytes):
        img = Image.open(io.BytesIO(image)).convert("RGB")
        img = img.resize((W // self.S, H // self.S)).filter(ImageFilter.GaussianBlur(0.75))   # 종이 결 빼기
        a = np.asarray(img, dtype=np.float64)
        self._sum = self._integral(a)
        self._sq = self._integral(a * a)

    @staticmethod
    def _integral(a: np.ndarray) -> np.ndarray:
        out = np.zeros((a.shape[0] + 1, a.shape[1] + 1, a.shape[2]))
        out[1:, 1:] = a.cumsum(0).cumsum(1)
        return out

    def _stats(self, x: float, y: float, w: float, h: float) -> tuple[np.ndarray, np.ndarray] | None:
        """px 좌표(1920×1088 기준) 상자의 채널별 (평균, 분산). 그림 밖은 잘라 낸다. 상자가 비면 None."""
        s = self.S
        h4, w4 = self._sum.shape[0] - 1, self._sum.shape[1] - 1
        x0, x1 = max(0, math.floor(x / s)), min(w4, math.ceil((x + w) / s))
        y0, y1 = max(0, math.floor(y / s)), min(h4, math.ceil((y + h) / s))
        if x1 <= x0 or y1 <= y0:
            return None

        def box(t: np.ndarray) -> np.ndarray:
            return t[y1, x1] - t[y0, x1] - t[y1, x0] + t[y0, x0]

        n = (x1 - x0) * (y1 - y0)
        mean = box(self._sum) / n
        return mean, np.maximum(box(self._sq) / n - mean * mean, 0.0)

    def at(self, x: float, y: float, w: float, h: float) -> float:
        """상자의 복잡도 (채널별 표준편차 평균)"""
        st = self._stats(x, y, w, h)
        return 0.0 if st is None else float(np.sqrt(st[1]).mean())

    def mean_rgb(self, x: float, y: float, w: float, h: float) -> tuple[float, float, float]:
        """상자의 채널별 평균 (0~255). 상자가 비면 흰 바탕으로 본다."""
        st = self._stats(x, y, w, h)
        return (255.0, 255.0, 255.0) if st is None else tuple(float(v) for v in st[0][:3])

    def brightness(self, x: float, y: float, w: float, h: float) -> float:
        """상자의 밝기 (0~255, 채널 평균). 상자가 비면 흰 바탕으로 본다."""
        st = self._stats(x, y, w, h)
        return 255.0 if st is None else float(st[0].mean())


# ── 자리 ──
def _page(x: float, bw: float) -> int:
    """덩어리 가운데 x 가 있는 면: 왼쪽 0, 오른쪽 1"""
    return 0 if x + bw / 2 < W / 2 else 1


def _x_range(page: int, bw: float) -> tuple[float, float]:
    """면 안에서 덩어리 왼쪽 끝이 놓일 수 있는 범위(px). 비면 lo > hi."""
    edge, fold = W * EDGE_X / 100, W * FOLD / 100
    lo, hi = (edge, W / 2 - fold) if page == 0 else (W / 2 + fold, W - edge)
    return lo, hi - bw


def _y_bands(bh: float) -> list[tuple[float, float]]:
    """덩어리 위끝 y 가 놓일 수 있는 두 띠(px): 위끝이 위에서 7~20%, 아래끝이 아래에서 7~20%"""
    top = (H * EDGE_Y / 100, H * BAND / 100)
    bottom = (max(H * EDGE_Y / 100, H * (100 - BAND) / 100 - bh), H * (100 - EDGE_Y) / 100 - bh)
    return [b for b in (top, bottom) if b[0] <= b[1]]


def _to_px(spot: dict) -> tuple[float, float]:
    """AI 가 %로 답하면 그대로, 픽셀로 답했으면(100 넘는 값) 그림 크기로 나눠 %로 본다"""
    x, y = float(spot["x"]), float(spot["y"])
    if x > 100 or y > 100:
        return x, y
    return x / 100 * W, y / 100 * H


def _push(x: float, y: float, bw: float, bh: float) -> tuple[float, float]:
    """여백 안으로 민다: 덩어리 가운데가 있는 면 안쪽으로"""
    lo, hi = _x_range(_page(x, bw), bw)
    x = min(max(x, lo), max(lo, hi))
    ylo, yhi = H * EDGE_Y / 100, H * (100 - EDGE_Y) / 100 - bh
    return x, min(max(y, ylo), max(ylo, yhi))


def _in_band(y: float, bh: float) -> bool:
    return any(lo - 1e-6 <= y <= hi + 1e-6 for lo, hi in _y_bands(bh))


def _gap_ok(x: float, y: float, bw: float, bh: float, placed: list[tuple[float, float, float, float]]) -> bool:
    """이미 놓은 덩어리와 2% 이상 띄었는지"""
    g = W * GAP
    return all(x + bw + g <= px or px + pw + g <= x or y + bh + g <= py or py + ph + g <= y
               for px, py, pw, ph in placed)


def _order_ok(x: float, y: float, bw: float, placed: list[tuple[float, float, float, float]]) -> bool:
    """읽는 순서: 앞 덩어리보다 (면, y)가 뒤"""
    return all((_page(x, bw), y) > (_page(px, pw), py) for px, py, pw, _ in placed)


def _score(busy: Busy, x: float, y: float, bw: float, bh: float) -> float:
    pad = W * BUSY_PAD
    return busy.at(x - pad, y - pad, bw + 2 * pad, bh + 2 * pad)


def _best_on(busy: Busy, pages: tuple[int, ...], near: tuple[float, float], bw: float, bh: float,
             placed: list[tuple[float, float, float, float]], limit: float,
             move_cost: float = MOVE_COST) -> tuple[float, float] | None:
    """주어진 면들의 띠 안에서 읽는 순서·간격을 지키고 복잡도가 limit 이하인 자리 중 (복잡도 + 거리 점수)가 가장 낮은 곳"""
    best: tuple[float, tuple[float, float]] | None = None
    for page in pages:
        lo, hi = _x_range(page, bw)
        for ylo, yhi in _y_bands(bh):
            for y in np.arange(ylo, yhi + 1e-6, GRID):
                for x in np.arange(lo, hi + 1e-6, GRID):
                    x, y = float(x), float(y)
                    if not (_order_ok(x, y, bw, placed) and _gap_ok(x, y, bw, bh, placed)):
                        continue
                    std = _score(busy, x, y, bw, bh)
                    if std > limit:
                        continue
                    score = std + move_cost * math.hypot(x - near[0], y - near[1])
                    if best is None or score < best[0]:
                        best = (score, (x, y))
    return best[1] if best else None


def _search(busy: Busy, near: tuple[float, float], bw: float, bh: float,
            placed: list[tuple[float, float, float, float]]) -> tuple[float, float] | None:
    """원래 자리와 같은 면을 먼저, 없으면 반대쪽 면의 띠 안에서 조용하고 가까운 곳"""
    home = _page(near[0], bw)
    for page in (home, 1 - home):
        found = _best_on(busy, (page,), near, bw, bh, placed, BUSY_LIMIT)
        if found:
            return found
    return None


def text_color(busy: Busy, x: float, y: float, bw: float, bh: float) -> str:
    """덩어리 자리(둘레 포함) 바탕과의 대비(WCAG)가 흰 글자 쪽이 비슷하거나 크면 light, 아니면 dark. AI가 고른 색은 쓰지 않는다 —
    어두운 밤 장면에도 dark를 고르고, 자리를 옮기면 다른 자리 색이 된다 (#77)."""
    pad = W * BUSY_PAD
    bg = luminance(busy.mean_rgb(x - pad, y - pad, bw + 2 * pad, bh + 2 * pad))
    on_white = (1.0 + 0.05) / (bg + 0.05)
    on_dark = (bg + 0.05) / (luminance(DARK_TEXT) + 0.05)
    return "light" if on_white >= on_dark * WHITE_BIAS else "dark"


def luminance(rgb: tuple[float, float, float]) -> float:
    """WCAG 상대 휘도 (0~1). 채널 평균 밝기는 파랑·보라 바탕을 실제보다 밝게 본다 (#77)."""
    def lin(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def calmest(busy: Busy, blocks: list[Block]) -> list[dict] | None:
    """settle도 다시 그리기도 자리를 못 찾았을 때: 복잡도 기준은 빼고 여백·띠·읽는 순서·간격만 지켜
    두 면을 통틀어 가장 덜 복잡한 곳. 그림을 안 보는 기본 자리보다 늘 낫거나 같다.
    글자색은 그 자리 밝기로 (text_color). 하나라도 놓을 곳이 없으면 None."""
    near = (DEFAULT_SPOT[0] / 100 * W, DEFAULT_SPOT[1] / 100 * H)   # 복잡도가 (거의) 같을 때만 왼쪽 위 쪽으로
    placed: list[tuple[float, float, float, float]] = []
    out: list[dict] = []
    for block in blocks:
        bw, bh = block_size(block)
        found = _best_on(busy, (0, 1), near, bw, bh, placed, math.inf, TIE_COST)
        if found is None:
            return None
        x, y = found
        placed.append((x, y, bw, bh))
        out.append({"x": round(x / W * 100, 1), "y": round(y / H * 100, 1), "color": text_color(busy, x, y, bw, bh)})
    return out


def settle(busy: Busy, blocks: list[Block], spots: list[dict]) -> list[dict] | None:
    """AI 자리를 여백 안으로 밀고, 띠·복잡도·읽는 순서·간격을 확인해 안 되면 옮긴다.
    덩어리마다 {"x": %, "y": %, "color"}. 글자색은 AI 답이 아니라 마지막 자리의 밝기로 (text_color). 하나라도 자리가 없으면 None."""
    placed: list[tuple[float, float, float, float]] = []
    out: list[dict] = []
    for i, block in enumerate(blocks):
        bw, bh = block_size(block)
        spot = spots[i] if i < len(spots) else {"x": DEFAULT_SPOT[0], "y": DEFAULT_SPOT[1], "color": DEFAULT_SPOT[2]}
        x, y = _push(*_to_px(spot), bw, bh)
        ok = (_in_band(y, bh) and _order_ok(x, y, bw, placed) and _gap_ok(x, y, bw, bh, placed)
              and _score(busy, x, y, bw, bh) <= BUSY_LIMIT)
        if not ok:
            found = _search(busy, (x, y), bw, bh, placed)
            if found is None:
                return None
            x, y = found
        placed.append((x, y, bw, bh))
        out.append({"x": round(x / W * 100, 1), "y": round(y / H * 100, 1), "color": text_color(busy, x, y, bw, bh)})
    return out


# ── AI 호출 ──
def chunk_page(text: str) -> tuple[list[str], list[Block], list[CostEntry]]:
    """쪽 글 → (줄, 덩어리, 비용). 줄이 하나면 AI를 부르지 않는다.
    AI 답이 틀리거나 호출이 실패해도 한 덩어리 한 문단으로 간다. 글은 늘 원문 줄 그대로."""
    lines = split_lines(text)
    if not lines:
        return [], [], []
    if len(lines) == 1:
        return lines, build_blocks(lines, [[[0]]]), []
    costs: list[CostEntry] = []
    idx = [[list(range(len(lines)))]]
    try:
        answer, cost = structured(
            node="layout:chunk",
            model=config.model_light,
            schema=TextChunking,
            system=prompt("text_chunks", lines="\n".join(f"{i}: {l}" for i, l in enumerate(lines))),
            user="이 쪽의 글을 덩어리로 나누세요.",
            reasoning="low",
        )
        costs.append(cost)
        idx = normalize_chunks(len(lines), answer.blocks, lines)
    except Exception as e:  # 글 내용은 로그에 남기지 않는다
        log.warning("덩어리 나누기 실패 → 한 덩어리: %s", type(e).__name__)
    return lines, build_blocks(lines, idx), costs


def _sanitize_spots(spots, n: int) -> list[dict]:
    """AI 자리 답을 % dict 목록으로. 개수가 다르거나 숫자가 아니면 [] (호출한 쪽이 기본 자리로 간다).
    100을 넘는 값은 픽셀로 답한 것이라 축마다 그림 크기로 나눠 %로 바꾼다."""
    if not isinstance(spots, (list, tuple)) or len(spots) != n:
        return []
    out: list[dict] = []
    for s in spots:
        try:
            x, y = float(s.x), float(s.y)
        except (AttributeError, TypeError, ValueError):
            return []
        if not (math.isfinite(x) and math.isfinite(y)):
            return []
        if x > 100:
            x = x / W * 100
        if y > 100:
            y = y / H * 100
        color = getattr(s, "color", None)
        out.append({"x": x, "y": y, "color": color if color in ("dark", "light") else "dark"})
    return out


def place_page(image: bytes, blocks: list[Block]) -> tuple[list[dict], list[CostEntry]]:
    """그림과 덩어리 → AI가 고른 자리 [{"x": %, "y": %, "color"}] (읽는 순서).
    settle() 전의 날것이다. 답이 이상하거나 호출이 실패하면 [] — 호출한 쪽이 기본 자리로 간다."""
    if not blocks:
        return [], []
    sizes = []
    for i, b in enumerate(blocks, 1):
        w, h = block_size(b)
        sizes.append(f"{i}번 덩어리: 가로 약 {w / W * 100:.0f}%, 세로 약 {h / H * 100:.0f}%")
    try:
        answer, cost = structured_image(
            node="layout:place",
            model=config.model_light,
            schema=TextPlacement,
            system=prompt("text_place", sizes="\n".join(sizes)),
            user=f"덩어리 {len(blocks)}개의 자리를 읽는 순서대로 답하세요.",
            image=image,
            reasoning="low",
        )
    except Exception as e:  # 글·그림 내용은 로그에 남기지 않는다
        log.warning("자리 찾기 호출 실패 → 기본 자리: %s", type(e).__name__)
        return [], []
    spots = _sanitize_spots(getattr(answer, "blocks", None), len(blocks))
    if not spots:
        log.warning("자리 찾기 답이 맞지 않음 → 기본 자리")
    return spots, [cost]
