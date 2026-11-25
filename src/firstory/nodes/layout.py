"""
쪽 글 배치 계산 (API 없음): 줄 나누기 → 덩어리 정리 → 크기 → 자리(여백·띠·복잡도·읽는 순서).
설계: docs/superpowers/specs/2026-11-04-text-blocks-design.md 2·3·5절.
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..config import config
from ..llm import prompt, structured, structured_image
from ..schemas import CostEntry, ReadingGuide, SoundPiece, SoundWord, TextBlock, TextChunking, TextPlacement, TextPlacementWithWord

log = logging.getLogger("firstory.layout")

W, H = 1920, 1088                  # 그림 기준 크기(px)
FONT_RATIO = 0.0235                # 글자 크기 = 그림 폭의 2.35% (프론트 StoryTextBlocks 2.35cqw와 같아야 한다, #98)
LINE_H = 1.55                      # 줄 높이 = 글자 크기 배수
PARA_GAP = 0.6                     # 문단 사이 = 줄 수
MAX_LINE = 0.38                    # 한 줄 최대 폭 = 그림 폭의 38%
EDGE_Y, EDGE_X, FOLD, BAND = 7, 5, 4, 20   # 위·아래 여백, 좌우 여백, 접히는 선 여백, 띠 (모두 %)
BUSY_LIMIT = 8.0                   # 복잡도(RGB 표준편차) 통과 기준
BUSY_PAD = 0.03                    # 복잡도를 재는 둘레 (그림 폭 대비)
GAP = 0.02                         # 덩어리 사이 최소 간격 (그림 폭 대비)
MAX_REDRAWS = 2                    # 한 번 실행에서 다시 그리는 쪽 상한
REDRAW_BUSY = 14.0                 # 다시 그리기 문턱: 자리를 못 찾아도 calmest가 몸 겹침 0·복잡도 이 이하면 다시 그리지 않는다 (#113)
CHAR_PAD = 0.015                   # 글이 피하는 캐릭터 칸을 사방으로 키우는 폭 (그림 폭 대비, #104)
OVERLAP_COST = 1.0                 # calmest: 캐릭터 몸(키우기 전 칸)과 겹친 넓이(px²)당 점수 — 한 줄만 조금 닿아도 복잡도보다 크다
MARGIN_COST = 0.005                # calmest: 키운 여백에만 걸친 넓이(px²)당 점수 — 한 줄이 여백에 걸친 약 2,000px² ≈ 복잡도 10
DEFAULT_SPOT = (5.0, 7.0, "dark")  # 마지막 안전판: 왼쪽 면 위 (그림을 못 읽거나 놓을 곳이 아예 없을 때만)
DARK_TEXT = (0x4A, 0x4A, 0x4A)     # 화면의 진한 글자색 (프론트 StoryTextBlocks)
WHITE_BIAS = 0.9                   # 흰 글자 대비가 진한 글자 대비의 이 배 이상이면 흰 글자 (비슷하면 흰 글자가 더 잘 읽힌다)

FONT_PX = round(W * FONT_RATIO)    # 45
LINE_PX = FONT_PX * LINE_H
FONT_PATH = Path(__file__).parents[1] / "assets/fonts/MemomentKkukkukk.woff2"
GRID = 8                           # 자리 찾기 격자(px)
MOVE_COST = 0.01                   # 원래 자리와 멀어진 만큼 더하는 점수(px당)
TIE_COST = 1e-5                    # calmest: 거리는 복잡도가 같을 때만 가르는 정도
SFX_LINE_H = 1.2                   # 의성어 조각 상자 높이 = 글자 크기 배수
SFX_EDGE_X, SFX_EDGE_Y, SFX_FOLD = 3, 4, 2   # 의성어 좌우 여백, 위·아래 여백, 접히는 선 여백 (%)
SFX_RADIUS = 0.15                  # 의성어를 밀 수 있는 반지름 (그림 폭 대비)
SFX_TOUCH_RADIUS = 0.25            # 손 동작(touch): 손 칸에서 조각 가운데까지 최대 거리 (그림 폭 대비, #119) — 손은 두 몸 칸 사이에 묻혀 있다

Block = list[list[str]]            # 덩어리 = 문단 > 줄

_SFX = re.compile(r"\*\*(.+?)\*\*")   # 본문의 의성어·의태어 표시 (render._SFX와 같다)
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


def questions_by_page(guide: Optional[ReadingGuide]) -> dict[int, list[str]]:
    """가이드 질문 → 쪽 번호별 질문 줄 (#100). 같은 쪽 질문이 여럿이면 가이드 순서대로 잇는다. 가이드가 없으면 {}."""
    out: dict[int, list[str]] = {}
    for q in (guide.prompts if guide else []):
        out.setdefault(q.after_page, []).extend(split_lines(q.text))
    return out


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
            if _quote_open(lines[i]):            # 이 줄의 따옴표 개수가 홀수 → 열림/닫힘이 바뀐다
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


_SENTENCE_STOP = re.compile(r'[.?!…]["”’\']*$')   # split_block: 문장이 끝난 줄 (wrap_line이 감은 줄 사이는 아님)
SPLIT_SKEW = 2 / 3                 # split_block: 문단 경계에서 큰 쪽이 전체 줄의 이 비율을 넘으면 줄 경계로 (#104)


def split_block(block: Block) -> list[Block] | None:
    """자리 없는 한 덩어리 → 양쪽 면에 놓을 두 덩어리 (#104). 문단·줄 순서와 글자는 그대로.
    문단 경계 중 가운데에 가장 가까운 곳(같으면 뒤쪽). 그 경계에서 큰 쪽이 SPLIT_SKEW를 넘거나 문단이 하나면
    줄 경계 중 가운데에 가장 가까운 곳(같으면 뒤쪽, 끊긴 문단은 둘로). 따옴표가 열린 채 끊기는 경계, 문장 중간(감긴 줄 사이)은 안 된다.
    나눌 곳이 없으면 None."""
    rows = [(pi, line) for pi, para in enumerate(block) for line in para]
    n = len(rows)
    if n < 2:
        return None

    def ok(k: int) -> bool:   # 앞 줄이 문장 끝이고 대사가 열려 있지 않다
        return bool(_SENTENCE_STOP.search(rows[k - 1][1].rstrip().removesuffix("**"))) and not _quote_open(
            " ".join(line for _, line in rows[:k]))

    def nearest(ks: list[int]) -> int | None:
        ks = [k for k in ks if ok(k)]
        return min(ks, key=lambda k: (abs(k - n / 2), -k)) if ks else None

    para_ks = [k for k in range(1, n) if rows[k][0] != rows[k - 1][0]]
    k = nearest(para_ks)
    if k is None or max(k, n - k) > n * SPLIT_SKEW:
        k = nearest(list(range(1, n)))
    if k is None:
        return None

    def regroup(part: list[tuple[int, str]]) -> Block:
        out: Block = []
        prev = None
        for pi, line in part:
            if pi != prev:
                out.append([])
                prev = pi
            out[-1].append(line)
        return out

    return [regroup(rows[:k]), regroup(rows[k:])]


def block_size(block: Block) -> tuple[float, float]:
    """(폭 px, 높이 px), 1920×1088 기준."""
    rows = [line for para in block for line in para]
    width = max((text_width(l) for l in rows), default=0.0)
    return width, (len(rows) + PARA_GAP * (len(block) - 1)) * FONT_PX * LINE_H


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


# ── 자리 ──
def _page(x: float, bw: float) -> int:
    """덩어리 가운데 x 가 있는 면: 왼쪽 0, 오른쪽 1"""
    return 0 if x + bw / 2 < W / 2 else 1


def side_of(i: int, n: int) -> int | None:
    """덩어리 n개 중 i번째가 놓일 면. 2덩어리면 1번 왼쪽(0)·2번 오른쪽(1)으로 고정, 그 밖에는 None(면 자유) (#95)"""
    return i if n == 2 else None


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
    """자리 % → px. 100 넘는 값이 있으면 이미 px로 보고 그대로 둔다"""
    x, y = float(spot["x"]), float(spot["y"])
    if x > 100 or y > 100:
        return x, y
    return x / 100 * W, y / 100 * H


def _push(x: float, y: float, bw: float, bh: float, page: int | None = None) -> tuple[float, float]:
    """여백 안으로 민다: page를 주면 그 면 안쪽으로, 아니면 덩어리 가운데가 있는 면 안쪽으로"""
    lo, hi = _x_range(_page(x, bw) if page is None else page, bw)
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


Rect = tuple[float, float, float, float]   # px x0, y0, x1, y1


def _pct_to_px(box: Rect) -> Rect:
    """% 칸 → px 칸"""
    return box[0] / 100 * W, box[1] / 100 * H, box[2] / 100 * W, box[3] / 100 * H


def _grow(rects, p: float) -> list[Rect]:
    """칸들을 사방으로 p px씩 키운다 (p < 0이면 줄인다)"""
    return [(x0 - p, y0 - p, x1 + p, y1 + p) for x0, y0, x1, y1 in rects]


def blockers(chars: "Chars") -> list[Rect]:
    """캐릭터 칸(%) → 글이 피할 px 칸. 사방으로 그림 폭의 CHAR_PAD씩 키운다 (#104)"""
    return _grow([_pct_to_px(b) for _, b in chars], W * CHAR_PAD)


def _overlap(x: float, y: float, bw: float, bh: float, avoid) -> float:
    """덩어리(x, y, bw, bh)와 칸들이 겹친 넓이 합 (px²)"""
    total = 0.0
    for x0, y0, x1, y1 in avoid:
        w = min(x + bw, x1) - max(x, x0)
        h = min(y + bh, y1) - max(y, y0)
        if w > 0 and h > 0:
            total += w * h
    return total


def rows_of(block: Block) -> list[tuple[float, float, float]]:
    """덩어리의 줄마다 (위끝 dy, 실제 글자 폭, 줄 높이) px. 글은 왼쪽 정렬이라 줄 오른쪽 끝은 줄마다 다르다"""
    out, dy = [], 0.0
    for i, para in enumerate(block):
        if i:
            dy += PARA_GAP * LINE_PX
        for line in para:
            out.append((dy, text_width(line), LINE_PX))
            dy += LINE_PX
    return out


def _unpad(avoid) -> list[Rect]:
    """blockers로 키운 칸 → 캐릭터 몸 칸 (px)"""
    return _grow(avoid, -W * CHAR_PAD)


def _overlap_rows(x: float, y: float, rows, avoid) -> float:
    """덩어리를 (x, y)에 놓았을 때 줄마다 실제 글자 상자가 칸들과 겹친 넓이 합 (px²)"""
    return sum(_overlap(x, y + dy, w, h, avoid) for dy, w, h in rows)


def _around(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    """바탕을 재는 상자 (x, y, w, h): 사방으로 그림 폭의 BUSY_PAD씩 키운다"""
    pad = W * BUSY_PAD
    return x - pad, y - pad, w + 2 * pad, h + 2 * pad


def _score(busy: Busy, x: float, y: float, bw: float, bh: float) -> float:
    return busy.at(*_around(x, y, bw, bh))


def _best_on(busy: Busy, pages: tuple[int, ...], near: tuple[float, float], bw: float, bh: float,
             placed: list[tuple[float, float, float, float]], limit: float,
             move_cost: float = MOVE_COST, avoid=(), strict: bool = True, rows=None) -> tuple[float, float] | None:
    """주어진 면들의 띠 안에서 읽는 순서·간격을 지키고 복잡도가 limit 이하인 자리 중 (복잡도 + 거리 점수)가 가장 낮은 곳.
    strict면 캐릭터 칸(avoid)과 겹치는 자리는 버리고, 아니면 겹친 넓이만큼 점수를 더한다 (#104).
    rows(rows_of)를 주면 겹침은 줄마다 실제 글자 폭으로 잰다 — 덩어리 네모로 재면 긴 줄 하나 때문에 빈 벽을 버린다"""
    best: tuple[float, tuple[float, float]] | None = None
    real = _unpad(avoid)

    def overlap(x: float, y: float, rects) -> float:
        return _overlap_rows(x, y, rows, rects) if rows is not None else _overlap(x, y, bw, bh, rects)

    for page in pages:
        lo, hi = _x_range(page, bw)
        for ylo, yhi in _y_bands(bh):
            for y in np.arange(ylo, yhi + 1e-6, GRID):
                for x in np.arange(lo, hi + 1e-6, GRID):
                    x, y = float(x), float(y)
                    if not (_order_ok(x, y, bw, placed) and _gap_ok(x, y, bw, bh, placed)):
                        continue
                    over = overlap(x, y, avoid) if avoid else 0.0
                    if strict and over > 0:
                        continue
                    std = _score(busy, x, y, bw, bh)
                    if std > limit:
                        continue
                    score = std + move_cost * math.hypot(x - near[0], y - near[1])
                    if over:   # 몸에 닿은 넓이는 크게, 여백에만 걸친 넓이는 작게 — 조용한 벽이 복잡한 물건 위보다 낫게
                        body = overlap(x, y, real)
                        score += OVERLAP_COST * body + MARGIN_COST * (over - body)
                    if best is None or score < best[0]:
                        best = (score, (x, y))
    return best[1] if best else None


def _search(busy: Busy, near: tuple[float, float], bw: float, bh: float,
            placed: list[tuple[float, float, float, float]], page: int | None = None, avoid=(), rows=None) -> tuple[float, float] | None:
    """원래 자리와 같은 면을 먼저, 없으면 반대쪽 면의 띠 안에서 조용하고 가까운 곳. page를 주면 그 면에서만"""
    if page is None:
        home = _page(near[0], bw)
        order = (home, 1 - home)
    else:
        order = (page,)
    for p in order:
        found = _best_on(busy, (p,), near, bw, bh, placed, BUSY_LIMIT, avoid=avoid, rows=rows)
        if found:
            return found
    return None


def text_color(busy: Busy, x: float, y: float, bw: float, bh: float) -> str:
    """덩어리 자리(둘레 포함) 바탕과의 대비(WCAG)가 흰 글자 쪽이 비슷하거나 크면 light, 아니면 dark. AI가 고른 색은 쓰지 않는다 —
    어두운 밤 장면에도 dark를 고르고, 자리를 옮기면 다른 자리 색이 된다 (#77)."""
    bg = luminance(busy.mean_rgb(*_around(x, y, bw, bh)))
    on_white = (1.0 + 0.05) / (bg + 0.05)
    on_dark = (bg + 0.05) / (luminance(DARK_TEXT) + 0.05)
    return "light" if on_white >= on_dark * WHITE_BIAS else "dark"


def _linear(c: float) -> float:
    """sRGB 채널(0~255) → 선형 값(0~1)"""
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[float, float, float]) -> float:
    """WCAG 상대 휘도 (0~1). 채널 평균 밝기는 파랑·보라 바탕을 실제보다 밝게 본다 (#77)."""
    r, g, b = (_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _spot(busy: Busy, x: float, y: float, bw: float, bh: float) -> dict:
    """px 자리 → {"x": %, "y": %, "color"}. 글자색은 그 자리 바탕으로 (text_color)"""
    return {"x": round(x / W * 100, 1), "y": round(y / H * 100, 1), "color": text_color(busy, x, y, bw, bh)}


def calmest(busy: Busy, blocks: list[Block], avoid=()) -> list[dict] | None:
    """settle도 다시 그리기도 자리를 못 찾았을 때: 복잡도 기준은 빼고 여백·띠·읽는 순서·간격만 지켜
    두 면을 통틀어 (캐릭터 칸과 겹친 넓이, 복잡도)가 가장 작은 곳(2덩어리면 1번은 왼쪽 면, 2번은 오른쪽 면 안에서만, #95, #104).
    그림을 안 보는 기본 자리보다 늘 낫거나 같다. 글자색은 그 자리 밝기로 (text_color). 하나라도 놓을 곳이 없으면 None."""
    near = (DEFAULT_SPOT[0] / 100 * W, DEFAULT_SPOT[1] / 100 * H)   # 복잡도가 (거의) 같을 때만 왼쪽 위 쪽으로
    placed: list[tuple[float, float, float, float]] = []
    out: list[dict] = []
    for i, block in enumerate(blocks):
        bw, bh = block_size(block)
        side = side_of(i, len(blocks))
        found = _best_on(busy, (0, 1) if side is None else (side,), near, bw, bh, placed, math.inf, TIE_COST,
                         avoid=avoid, strict=False, rows=rows_of(block))
        if found is None:
            return None
        x, y = found
        placed.append((x, y, bw, bh))
        out.append(_spot(busy, x, y, bw, bh))
    return out


def _cost(busy: Busy, blocks: list[Block], spots: list[dict], avoid=()) -> tuple[float, float]:
    """(캐릭터 몸과 겹친 넓이 합, 가장 복잡한 자리의 복잡도 + 여백에만 걸친 넓이 × MARGIN_COST). 겹침은 줄마다"""
    real = _unpad(avoid)
    body = pad = 0.0
    worst = 0.0
    for b, s in zip(blocks, spots):
        x, y = s["x"] / 100 * W, s["y"] / 100 * H
        rows = rows_of(b)
        body += _overlap_rows(x, y, rows, real)
        pad += _overlap_rows(x, y, rows, avoid)
        worst = max(worst, _score(busy, x, y, *block_size(b)))
    return body, worst + MARGIN_COST * (pad - body)


def calmest_pick(busy: Busy, blocks: list[Block], avoid=()) -> tuple[list[Block], list[dict]] | None:
    """조용한 곳이 없을 때의 (덩어리, 자리). 후보는 받은 덩어리 그대로, 2덩어리면 합친 한 덩어리, 1덩어리면 split_block으로 나눈 둘.
    _cost (겹친 넓이, 가장 복잡한 자리)가 가장 작은 후보. 같으면 앞 후보 — 2덩어리는 나눈 쪽, 1덩어리는 그대로 (#95, #104).
    놓을 곳이 없으면 None."""
    cands = [blocks]
    if len(blocks) == 2:
        cands.append(merge(blocks))
    elif len(blocks) == 1:
        parts = split_block(blocks[0])
        if parts is not None:
            cands.append(parts)
    best: tuple[tuple[float, float], list[Block], list[dict]] | None = None
    for bl in cands:
        spots = calmest(busy, bl, avoid)
        if spots is None:
            continue
        cost = _cost(busy, bl, spots, avoid)
        if best is None or cost < best[0]:
            best = (cost, bl, spots)
    return (best[1], best[2]) if best else None


def settle(busy: Busy, blocks: list[Block], spots: list[dict], avoid=()) -> list[dict] | None:
    """AI 자리를 여백 안으로 밀고, 띠·복잡도·읽는 순서·간격·캐릭터 칸(avoid, #104)을 확인해 안 되면 옮긴다.
    2덩어리면 1번은 왼쪽 면, 2번은 오른쪽 면 안에서만 밀고 찾는다 (#95).
    덩어리마다 {"x": %, "y": %, "color"}. 글자색은 AI 답이 아니라 마지막 자리의 밝기로 (text_color). 하나라도 자리가 없으면 None."""
    placed: list[tuple[float, float, float, float]] = []
    out: list[dict] = []
    for i, block in enumerate(blocks):
        bw, bh = block_size(block)
        spot = spots[i] if i < len(spots) else {"x": DEFAULT_SPOT[0], "y": DEFAULT_SPOT[1], "color": DEFAULT_SPOT[2]}
        side = side_of(i, len(blocks))
        rows = rows_of(block)
        x, y = _push(*_to_px(spot), bw, bh, side)
        ok = (_in_band(y, bh) and _order_ok(x, y, bw, placed) and _gap_ok(x, y, bw, bh, placed)
              and _overlap_rows(x, y, rows, avoid) == 0 and _score(busy, x, y, bw, bh) <= BUSY_LIMIT)
        if not ok:
            found = _search(busy, (x, y), bw, bh, placed, side, avoid, rows)
            if found is None:
                return None
            x, y = found
        placed.append((x, y, bw, bh))
        out.append(_spot(busy, x, y, bw, bh))
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


Chars = list[tuple[str, tuple[float, float, float, float]]]   # (이름, % 칸 x0, y0, x1, y1)


def _sanitize_chars(chars) -> Chars:
    """AI 캐릭터 칸 목록 → [(이름, 칸 %)]. 이상한 칸은 그 칸만 뺀다 (#102, #104)"""
    out: Chars = []
    try:
        items = list(chars or [])
    except TypeError:
        return out
    for c in items:
        box = _sanitize_box(getattr(c, "box", None))
        if box is not None:
            out.append((str(getattr(c, "name", "") or ""), box))
    return out


def _sanitize_word(spot, chars: Chars) -> dict | None:
    """AI 의성어 답 → {"owner", "kind": face|object|touch, "source": (x0, y0, x1, y1) %, "chars": 맨 위 캐릭터 칸} (#102, #104, #119).
    근원 칸이 이상하거나 종류가 face·object·touch가 아니면 None."""
    if spot is None:
        return None
    kind = getattr(spot, "source_kind", None)
    source = _sanitize_box(getattr(spot, "source_box", None))
    if kind not in ("face", "object", "touch") or source is None:
        return None
    return {"owner": str(getattr(spot, "owner", "") or ""), "kind": kind, "source": source, "chars": list(chars)}


def _sanitize_box(box) -> tuple[float, float, float, float] | None:
    """주인 칸 → (x0, y0, x1, y1) %. 숫자가 아니거나 0~100 밖이거나 뒤집혔으면 None (칸 없이 간다)"""
    try:
        v = tuple(float(getattr(box, k)) for k in ("x0", "y0", "x1", "y1"))
    except (AttributeError, TypeError, ValueError):
        return None
    if not all(math.isfinite(a) and 0 <= a <= 100 for a in v) or v[0] >= v[2] or v[1] >= v[3]:
        return None
    return v


GRID_NOTE = "그림에 10% 간격으로 빨간 눈금과 숫자(%)를 그려 두었다. 자리를 % 로 읽을 때 눈금을 쓴다. 눈금은 실제 그림에는 없다."


def with_grid(image: bytes) -> bytes:
    """그림에 10% 간격 빨간 눈금과 숫자를 그린다 (AI가 % 자리를 읽기 쉽게, #92)"""
    img = Image.open(io.BytesIO(image)).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    font = ImageFont.load_default(size=max(14, img.width // 70))
    for k in range(1, 10):
        x, y = img.width * k / 10, img.height * k / 10
        d.line([(x, 0), (x, img.height)], fill=(255, 0, 0, 110), width=2)
        d.line([(0, y), (img.width, y)], fill=(255, 0, 0, 110), width=2)
        d.text((x + 4, 4), f"{k * 10}", fill=(255, 0, 0, 230), font=font)
        d.text((4, y + 2), f"{k * 10}", fill=(255, 0, 0, 230), font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def place_page(image: bytes, blocks: list[Block], sfx: "SfxAsk | None" = None, grid: bool = True
               ) -> tuple[list[dict], Chars, dict | None, list[CostEntry]]:
    """그림과 덩어리 → (AI가 고른 자리 [{"x": %, "y": %, "color"}] (읽는 순서), 캐릭터 칸 (#104),
    의성어 근원 답 (_sanitize_word, sfx가 있을 때만), 비용).
    settle() 전의 날것이다. 답이 이상하거나 호출이 실패하면 자리 [] — 호출한 쪽이 기본 자리로 간다.
    grid면 그림에 10% 눈금을 그려 보낸다(그리다 터지면 원래 그림)."""
    if not blocks:
        return [], [], None, []
    sizes = []
    for i, b in enumerate(blocks, 1):
        w, h = block_size(b)
        sizes.append(f"{i}번 덩어리: 가로 약 {w / W * 100:.0f}%, 세로 약 {h / H * 100:.0f}%")
    if grid:
        try:
            image = with_grid(image)
        except Exception as e:  # noqa: BLE001 — 눈금이 자리 찾기를 막지 않는다
            log.warning("눈금 그리기 실패 → 원래 그림으로: %s", type(e).__name__)
            grid = False
    system = prompt("text_place", sizes="\n".join(sizes), grid=GRID_NOTE if grid else "")
    user = f"덩어리 {len(blocks)}개의 자리와 캐릭터 칸을 답하세요. 자리는 읽는 순서대로."
    schema = TextPlacement
    if sfx is not None:
        try:   # 의성어 준비가 터지면 의성어 없이 예전 호출로 (글 자리·칸은 그대로 받는다)
            sys_w = system + "\n\n" + prompt("text_place_word", word=sfx.word, text=sfx.text,
                                              cast="\n".join(f"- {n}: {look}" for n, look in sfx.cast) or "- (없음)")
        except Exception as e:  # noqa: BLE001
            log.warning("의성어 자리 묻기 준비 실패 → 의성어 없이: %s", type(e).__name__)
            sfx = None
        else:
            system = sys_w
            user += " 의성어 자리도 답하세요."
            schema = TextPlacementWithWord
    try:
        answer, cost = structured_image(
            node="layout:place",
            model=config.model_light,
            schema=schema,
            system=system,
            user=user,
            image=image,
            reasoning="low",
        )
    except Exception as e:  # 글·그림 내용은 로그에 남기지 않는다
        log.warning("자리 찾기 호출 실패 → 기본 자리: %s", type(e).__name__)
        return [], [], None, []
    spots = _sanitize_spots(getattr(answer, "blocks", None), len(blocks))
    if not spots:
        log.warning("자리 찾기 답이 맞지 않음 → 기본 자리")
    chars = _sanitize_chars(getattr(answer, "characters", None))
    word = _sanitize_word(getattr(answer, "sound_word", None), chars) if sfx is not None else None
    return spots, chars, word, [cost]


# ── 의성어·의태어 (#92) ──
@dataclass
class SfxAsk:
    word: str                          # 별표를 뺀 말
    text: str                          # 그 쪽 본문 (누구의 소리인지 알려고)
    cast: list[tuple[str, str]]        # (이름, 그림에서 알아볼 짧은 외형)


def sound_words(text: str) -> list[str]:
    """본문의 **…** 말을 나온 순서대로 (별표·앞뒤 공백 없이)"""
    return [m.strip() for m in _SFX.findall(text or "") if m.strip()]


def short_look(visual_description: str) -> str:
    """외형 문단의 첫 문장만, 120자까지"""
    first = (visual_description or "").split(". ")[0].strip().rstrip(".")
    return first[:120]


PIECE_RATIO = 0.025                # 의성어 조각 글자 크기 = 그림 폭의 2.5% (#102, 손글씨 예시 비율)
HUES: list[tuple[str, tuple[int, int, int]]] = [   # 의성어 색. 처음 팔레트(#102)와 색상은 같고 밝기만 0.10으로 진하게 (#117)
    ("#6735D0", (0x67, 0x35, 0xD0)),   # 보라
    ("#993B0A", (0x99, 0x3B, 0x0A)),   # 주황
    ("#AE1C2A", (0xAE, 0x1C, 0x2A)),   # 빨강
    ("#2055B1", (0x20, 0x55, 0xB1)),   # 파랑
    ("#1B6537", (0x1B, 0x65, 0x37)),   # 초록
]
WHITE = ("#FFFFFF", (0xFF, 0xFF, 0xFF))   # 어두운 바탕
GRAY = ("#4A4A4A", (0x4A, 0x4A, 0x4A))    # 진한 5색·흰색 모두 안 될 때
MIN_CONTRAST = 3.0                 # 의성어 색 후보가 되는 WCAG 대비


def split_word(word: str) -> list[str]:
    """같은 두 글자가 두 번 반복되는 4글자 말(데굴데굴)만 두 조각, 나머지는 한 조각. 공백은 빼고 본다 (#102)"""
    w = word.replace(" ", "")
    if len(w) == 4 and w[:2] == w[2:]:
        return [w[:2], w[2:]]
    return [w]


def piece_size(text: str) -> tuple[float, float]:
    """조각 상자 크기(px): 본문 글꼴로 잰 폭을 조각 글자 크기 비율만큼 바꾼다"""
    return text_width(text) * PIECE_RATIO / FONT_RATIO, W * PIECE_RATIO * SFX_LINE_H


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """두 색의 WCAG 대비 (1~21)"""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    """sRGB(0~255) → CIELAB (D65)"""
    r, g, b = (_linear(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """두 색의 차이 (CIE76 ΔE)"""
    return math.dist(_lab(a), _lab(b))


def pick_color(busy: Busy, boxes: list[tuple[float, float, float, float]], word: str) -> str:
    """조각 상자들(px x, y, w, h) 둘레 배경에서 읽히는 색 하나 (#102, #117).
    말(md5)로 HUES 시작 색을 정해 차례로 보고, 모든 조각 배경과 대비 3:1 이상인 첫 색. 같은 말은 같은 색.
    다 안 되면 흰색 → 진한 회색, 그래도 없으면 대비 최솟값이 가장 큰 색."""
    bgs = [busy.mean_rgb(*_around(*box)) for box in boxes]
    start = hashlib.md5(word.encode("utf-8")).digest()[0] % len(HUES)
    order = HUES[start:] + HUES[:start] + [WHITE, GRAY]

    def worst(rgb: tuple[int, int, int]) -> float:
        return min(contrast(rgb, bg) for bg in bgs)

    for hexc, rgb in order:
        if worst(rgb) >= MIN_CONTRAST:
            return hexc
    return max(order, key=lambda c: worst(c[1]))[0]


def _word_ok(cx: float, cy: float, ww: float, wh: float, boxes: list[tuple[float, float, float, float]]) -> bool:
    x0, y0 = cx - ww / 2, cy - wh / 2
    x1, y1 = x0 + ww, y0 + wh
    if x0 < W * SFX_EDGE_X / 100 or x1 > W * (100 - SFX_EDGE_X) / 100:
        return False
    if y0 < H * SFX_EDGE_Y / 100 or y1 > H * (100 - SFX_EDGE_Y) / 100:
        return False
    fold = W * SFX_FOLD / 100
    if x1 > W / 2 - fold and x0 < W / 2 + fold:
        return False
    return _gap_ok(x0, y0, ww, wh, boxes)


def _rect_dist(pt: tuple[float, float], box: tuple[float, float, float, float]) -> float:
    """점과 칸(x0, y0, x1, y1) 사이 거리. 칸 안이면 0"""
    dx = max(box[0] - pt[0], 0.0, pt[0] - box[2])
    dy = max(box[1] - pt[1], 0.0, pt[1] - box[3])
    return math.hypot(dx, dy)


def _closer_to_source(pt: tuple[float, float], source: tuple[float, float, float, float],
                      others: list[tuple[float, float, float, float]]) -> bool:
    """조각 가운데가 근원 칸에 다른 캐릭터 칸 어느 것보다 가까운가 (px, #102)"""
    d = _rect_dist(pt, source)
    return all(d < _rect_dist(pt, o) for o in others)


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _others(kind: str, source: tuple[float, float, float, float],
            chars: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    """근원보다 가까우면 안 되는 캐릭터 칸 (px) (#102).
    face: 얼굴 가운데를 덮는 칸은 모두 뺀다 — 얼굴 주인과, 안긴 장면에서 그 얼굴을 품은 캐릭터(실험 11/16, 안긴 쪽 2/4).
    object: 물건과 가장 많이 겹치는 캐릭터 하나(든 캐릭터)만 뺀다. 같으면 더 작은 칸. 물건에 살짝 걸친 다른 캐릭터는 남는다.
    touch: 손 칸과 겹치는 캐릭터(손 주인과 손이 닿은 캐릭터)는 모두 뺀다 (#119)."""
    if kind == "touch":
        return [c for c in chars if not _overlaps(source, c)]
    if kind == "face":
        mid = ((source[0] + source[2]) / 2, (source[1] + source[3]) / 2)
        return [c for c in chars if _rect_dist(mid, c) > 0]

    def inter(c):
        w = min(source[2], c[2]) - max(source[0], c[0])
        h = min(source[3], c[3]) - max(source[1], c[1])
        return w * h if w > 0 and h > 0 else 0.0

    hits = [c for c in chars if inter(c) > 0]
    if not hits:
        return list(chars)
    mine = max(hits, key=lambda c: (inter(c), -(c[2] - c[0]) * (c[3] - c[1])))
    return [c for c in chars if c is not mine]


@dataclass
class _WordScene:
    """조각을 놓을 때 보는 것 (모두 px)"""
    kind: str                                          # face | object | touch
    source: tuple[float, float, float, float]          # 근원 칸 x0, y0, x1, y1
    chars: list[tuple[float, float, float, float]]     # 모든 캐릭터 칸, CHAR_PAD만큼 키운 것 (겹치면 안 됨, #108)
    others: list[tuple[float, float, float, float]]    # 근원보다 가까우면 안 되는 캐릭터 칸
    blocks: list[tuple[float, float, float, float]]    # 글 덩어리 x, y, w, h (_gap_ok 모양)


def _piece_ok(sc: _WordScene, cx: float, cy: float, pw: float, ph: float) -> bool:
    """여백·접히는 선·글 덩어리 간격, 캐릭터 칸과 안 겹침, 근원이 다른 캐릭터보다 가까움"""
    if not _word_ok(cx, cy, pw, ph, sc.blocks):
        return False
    rect = (cx - pw / 2, cy - ph / 2, cx + pw / 2, cy + ph / 2)
    if any(_overlaps(rect, c) for c in sc.chars):
        return False
    return _closer_to_source((cx, cy), sc.source, sc.others)


def _offsets() -> list[tuple[float, float]]:
    """반지름 안 격자 이동 (가까운 순, 사방)"""
    r = W * SFX_RADIUS
    n = int(r // GRID)
    rng = range(-n, n + 1)
    out = []
    for i in rng:
        for j in rng:
            dx, dy = i * GRID, j * GRID
            if dx * dx + dy * dy <= r * r:
                out.append((dx, dy))
    out.sort(key=lambda d: d[0] * d[0] + d[1] * d[1])
    return out


def _place_pair(sc: _WordScene, size: tuple[float, float]) -> list[tuple[float, float]] | None:
    """두 조각을 근원 양옆에. 왼쪽 조각은 근원 왼쪽에서 바깥(왼쪽)으로만, 오른쪽 조각은 오른쪽으로만 움직이며
    각자 가장 가까운 자리를 찾는다 — 그림책 장면은 한쪽이 옆 캐릭터에 막히기 쉬워 거울 대칭으로는 거의 안 놓인다(실험 11/16).
    시작 높이는 face면 근원 위끝, object면 근원 가운데. 위아래로 움직일 수 있되 face는 조각 아래끝이 근원 아래끝을,
    object는 가운데가 근원 칸 ± 조각 높이를 넘지 않는다. 두 조각 높이 차이는 조각 둘 높이까지."""
    pw, ph = size
    x0, y0, x1, y1 = sc.source
    g = W * 0.01
    base = y0 if sc.kind == "face" else (y0 + y1) / 2
    got = []
    for sx, sign in ((x0 - g - pw / 2, -1), (x1 + g + pw / 2, 1)):
        hit = None
        for dx, dy in _offsets():
            if dx * sign < 0:
                continue
            x, y = sx + dx, base + dy
            if sc.kind == "face" and y + ph / 2 > y1:
                continue
            if sc.kind == "object" and not (y0 - ph <= y <= y1 + ph):
                continue
            if _piece_ok(sc, x, y, pw, ph):
                hit = (x, y)
                break
        if hit is None:
            return None
        got.append(hit)
    (lx, ly), (rx, ry) = got
    if abs(ly - ry) > 2 * ph or lx + pw / 2 > rx - pw / 2:
        return None
    return got


def _place_one(sc: _WordScene, size: tuple[float, float]) -> tuple[float, float] | None:
    """한 조각을 근원 바로 위 가운데에서 시작해 가까운 곳으로. face는 조각 아래끝이 근원 아래끝보다 아래로 가지 않고,
    object는 근원 위끝보다 조각 하나 높이까지만 올라가고 근원 아래끝보다 아래로 가지 않는다(가운데 기준)."""
    pw, ph = size
    x0, y0, x1, y1 = sc.source
    cx, cy = (x0 + x1) / 2, y0 - W * 0.01 - ph / 2
    for dx, dy in _offsets():
        x, y = cx + dx, cy + dy
        if sc.kind == "face" and y + ph / 2 > y1:
            continue
        if sc.kind == "object" and not (y0 - ph <= y <= y1):
            continue
        if _piece_ok(sc, x, y, pw, ph):
            return x, y
    return None


def _place_touch(sc: _WordScene, size: tuple[float, float]) -> tuple[float, float] | None:
    """손 동작: 한 조각을 손 칸에서 가장 가까운 곳에 (#119). 손은 두 몸 칸 사이라 바로 옆은 다 막힌다 —
    손 칸 가운데 둘레를 격자로 보고 _piece_ok인 자리 중 (손 칸까지 거리, 손 가운데까지 거리)가 가장 작은 곳.
    손 칸까지 거리가 SFX_TOUCH_RADIUS를 넘으면 버린다. 없으면 None."""
    pw, ph = size
    x0, y0, x1, y1 = sc.source
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = W * SFX_TOUCH_RADIUS
    n = int((r + max(x1 - x0, y1 - y0) / 2) // GRID)
    best: tuple[tuple[float, float], tuple[float, float]] | None = None
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x, y = cx + i * GRID, cy + j * GRID
            d = _rect_dist((x, y), sc.source)
            if d > r:
                continue
            key = (d, math.hypot(x - cx, y - cy))
            if (best is None or key < best[0]) and _piece_ok(sc, x, y, pw, ph):
                best = (key, (x, y))
    return best[1] if best else None


def place_word(busy: Busy, word: str, spot: dict | None, blocks: list[TextBlock]) -> SoundWord | None:
    """근원·캐릭터 칸(_sanitize_word) → 조각 1~2개 자리와 색 (#102).
    반복 4글자는 두 조각을 근원 양옆에, 안 되면 원래 말 한 조각으로, 그래도 안 되면 None.
    손 동작(touch)은 늘 원래 말 한 조각을 손 칸 가까이 (_place_touch, #119)."""
    if spot is None or not word or not word.strip():
        return None

    source = _pct_to_px(spot["source"])
    chars = [_pct_to_px(b) for _, b in spot.get("chars", [])]
    others = _others(spot["kind"], source, chars)
    block_px = []
    for b in blocks:
        bw, bh = block_size(b.paragraphs)
        block_px.append((b.x / 100 * W, b.y / 100 * H, bw, bh))
    # 캐릭터를 절대 가리지 않게: 칸은 윤곽에 붙어 오니 사방으로 여유를 둔다 (#108)
    sc = _WordScene(kind=spot["kind"], source=source, chars=_grow(chars, W * CHAR_PAD), others=others, blocks=block_px)

    whole = word.replace(" ", "")
    if spot["kind"] == "touch":
        one = _place_touch(sc, piece_size(whole))
        return _word(busy, word, spot, [(whole, *one, "center")]) if one else None
    parts = split_word(word)
    if len(parts) == 2:
        pw = max(piece_size(t)[0] for t in parts)
        pair = _place_pair(sc, (pw, piece_size(parts[0])[1]))
        if pair:
            return _word(busy, word, spot, [(parts[0], *pair[0], "left"), (parts[1], *pair[1], "right")])
    one = _place_one(sc, piece_size(whole))
    return _word(busy, word, spot, [(whole, *one, "center")]) if one else None


def _word(busy: Busy, word: str, spot: dict, placed: list[tuple[str, float, float, str]]) -> SoundWord:
    """조각 자리(px 가운데) → 색을 고른 SoundWord"""
    rects = []
    for t, cx, cy, _ in placed:
        pw, ph = piece_size(t)
        rects.append((cx - pw / 2, cy - ph / 2, pw, ph))
    return SoundWord(text=word, color=pick_color(busy, rects, word),
                     pieces=[SoundPiece(text=t, x=round(cx / W * 100, 1), y=round(cy / H * 100, 1), side=side)
                             for t, cx, cy, side in placed],
                     owner=spot.get("owner") or None)
