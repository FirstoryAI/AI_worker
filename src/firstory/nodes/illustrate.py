"""
🔒 ④ 일러스트: 캐릭터 시트(주인공 + 조연) 각 1장 → 페이지마다 그 장면에 나오는 캐릭터의 시트만 참조로 넣고 병렬 생성.
자동 재시도는 콘텐츠 정책에 막혔을 때만 한 번 — 장면 설명을 순화해서 다시 그린다 (#37).
그래도 실패한 페이지는 failed 로 두고, 뷰어 [재시도]로 그 페이지만.
"""
from __future__ import annotations

import base64
import io
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from .. import storage
from ..config import config
from openai import BadRequestError
from PIL import Image

from ..llm import client, prompt, structured
from ..schemas import CharacterSheet, CostEntry, Illustrations, PageImage, SoftenedScene, StoryText, TextBlock
from .layout import DEFAULT_SPOT, H, MAX_REDRAWS, W, Busy, Block, block_size, build_blocks, calmest, chunk_page, merge, place_page, settle, split_lines, wrap_line
from ..state import PipelineState

log = logging.getLogger("firstory.illustrate")

# 테스트용 훅: (prompt, [ref_png...]) -> png bytes
_override: Optional[Callable[[str, list[bytes]], bytes]] = None


def set_image_override(fn):
    global _override
    _override = fn


class PolicyBlocked(Exception):
    """이미지 모델의 콘텐츠 정책(safety system)에 막힘. 테스트 훅도 이걸 던져 재시도를 흉내 낸다."""


def _policy(e: BadRequestError) -> Exception:
    code = getattr(e, "code", None) or (getattr(e, "body", None) or {}).get("code")
    if code in ("moderation_blocked", "content_policy_violation") or "safety system" in str(e).lower():
        return PolicyBlocked(str(e)[:300])
    return e


def _usage(res) -> tuple[int, int]:
    u = getattr(res, "usage", None)
    return (getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0) if u else (0, 0)


def _format_args() -> dict:
    return ({"output_format": config.image_format, "output_compression": config.image_compression}
            if config.image_format != "png" else {})


def _gen(prompt_text: str, size: Optional[str] = None) -> tuple[bytes, int, int]:
    """→ (그림 bytes, input_tokens, output_tokens). 이미지 비용은 토큰으로 매겨진다.
    시트라 config.sheet_size·config.image_format으로 받는다 (#80). 저장 key 확장자는 _ext로 정한다."""
    if _override:
        return _override(prompt_text, []), 0, 0
    try:
        res = client().images.generate(
            model=config.image_model, prompt=prompt_text, size=size or config.sheet_size, quality=config.image_quality, n=1,
            **_format_args(),
        )
    except BadRequestError as e:
        raise _policy(e) from e
    return base64.b64decode(res.data[0].b64_json), *_usage(res)


def _edit(prompt_text: str, refs: list[tuple[str, bytes]], size: Optional[str] = None) -> tuple[bytes, int, int]:
    """refs: [(이름, 그림 bytes)]. 여러 장이면 리스트로 넘긴다 (gpt-image-2는 참조 이미지 여러 장 지원).
    쪽·표지라 config.image_format으로 받는다 (#32). 저장 key 확장자는 _ext로 실제 바이트를 보고 정한다."""
    if _override:
        return _override(prompt_text, [b for _, b in refs]), 0, 0
    images = _attach(refs)
    try:
        res = client().images.edit(
            model=config.image_model,
            image=images if len(images) > 1 else images[0],
            prompt=prompt_text,
            size=size or config.image_size,
            quality=config.image_quality,
            n=1,
            **({"input_fidelity": "high"} if config.image_model.startswith("gpt-image-1") else {}),  # 1/1.5 전용
            **_format_args(),
        )
    except BadRequestError as e:
        raise _policy(e) from e
    return base64.b64decode(res.data[0].b64_json), *_usage(res)


def _soften(scene: str) -> tuple[str, CostEntry]:
    s, cost = structured(
        node="illustrate:soften",
        model=config.model_light,
        schema=SoftenedScene,
        system=prompt("soften_image_prompt", text=scene),
        user="같은 장면을 정책에 걸리지 않게 다시 쓰세요.",
        reasoning="low",
    )
    return s.text, cost


def _draw(draw: Callable[[str], tuple[bytes, int, int]], scene: str, what: str, costs: list[CostEntry]):
    """draw(scene)으로 그린다. 콘텐츠 정책에 막히면 장면만 순화해서 한 번 더 (#37).
    로그에는 어느 그림인지만 남긴다 — 장면 설명은 부모 입력에서 나와서 남기지 않는다."""
    try:
        return draw(scene)
    except PolicyBlocked:
        log.warning("그림 콘텐츠 정책 위반, 장면을 순화해 다시 그림: %s", what)
        softened, cost = _soften(scene)
        costs.append(cost)
        try:
            return draw(softened)
        except PolicyBlocked:
            log.warning("순화한 뒤에도 콘텐츠 정책 위반: %s", what)
            raise


_MIME = {"png": "image/png", "webp": "image/webp", "jpg": "image/jpeg"}


def _attach(refs: list[tuple[str, bytes]]) -> list[tuple[str, bytes, str]]:
    """첨부 파일 이름·MIME을 실제 바이트 형식에 맞춘다. 줄이지 않은 시트는 WebP 그대로 간다 (#80)."""
    out = []
    for name, data in refs:
        ext = _ext(data)
        out.append((f"{name.rsplit('.', 1)[0]}.{ext}", data, _MIME[ext]))
    return out


def _ext(data: bytes) -> str:
    """저장 key 확장자. 설정이 아니라 받은 바이트로 정해서 key와 내용이 어긋나지 않게 한다 (Spring이 확장자로 Content-Type을 정함)."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    return "png"


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name)


def sheet_prompt(c: CharacterSheet, style: str) -> str:
    return "\n".join([
        "Character reference sheet for a children's picture book. Single character, full body, neutral standing pose, facing slightly left, plain cream background.",
        f"Character: {c.visual_description}",
        f"Style: {style}",
        "No text, no labels, no multiple poses — one clean full-body view.",
    ])


LINE_WARN = 5   # 한 쪽 글이 이 줄 수를 넘으면 경고만 남긴다 (글이 길면 덩어리가 커서 자리 찾기가 어렵다)
PAD_W, PAD_H = 4, 5   # 덩어리 크기에 더하는 여유 (그림 폭·높이 대비 %)


def layout_prompt(sizes: list[tuple[float, float]], where: Optional[list[str]] = None) -> str:
    """그림에 글 자리를 남기는 지시. sizes: 덩어리마다 (폭 px, 높이 px) — layout.block_size, 1920×1088 기준.
    where: 다시 그릴 때 덩어리마다 "left top" 같은 자리. 첫 그리기에는 쓰지 않는다."""
    # 빈 곳을 "area n: 가로 n%"처럼 자리로 적으면 그림 모델이 빈 판·상자를 그려 넣는다 → 구도로만 말한다
    spans = []
    for i, (w, h) in enumerate(sizes, 1):
        span = f"one open stretch roughly {round(w / W * 100 + PAD_W)}% of the image wide and {round(h / H * 100 + PAD_H)}% tall"
        if where and i <= len(where):
            span += f" toward the {where[i - 1]}"
        spans.append(span)
    return (
        "Layout: one continuous wide picture. Do not draw any vertical line, seam, crease, fold or gutter down the middle; "
        "the scene runs straight across the center. "
        "Story text will be printed over the picture later, so compose the scene with generous open space: "
        "the plain wall, sky, floor or blanket simply continues there, uninterrupted — " + "; ".join(spans) + ", "
        "toward the top or the bottom of the picture (not the middle height), each within the left half or the right half (not across the vertical center). "
        "This open space must look like a natural part of the scene, with the same color, texture and light as its surroundings. "
        "Never draw any box, panel, frame, card, sheet of paper, sign, label, speech bubble, blank rectangle or lighter patch "
        "to mark where text goes. "
        "Keep the characters' faces and ears and other important objects out of that open space, "
        "and never put a face at the vertical center of the image."
    )


def cover_prompt(story: StoryText, setting: Optional[str] = None) -> str:
    lines = [f"Front cover of a children's picture book. {len(story.characters)} reference image(s) are attached, one per character, in this order:"]
    for i, c in enumerate(story.characters, 1):
        lines.append(f"  Reference {i} = {c.name} ({c.role}): {c.visual_description}")
    lines += [
        "Draw each character EXACTLY as in its reference (same species, colors, markings, proportions, outfit). Do not redesign, do not add other characters.",
        "The protagonist is the clear focus, warm and inviting, in a simple setting that hints at the story.",
        f"Story setting (for mood only): {setting if setting is not None else story.pages[0].image_prompt if story.pages else ''}",
        f"Style: {story.style_guide}",
        f'Put the book title in Korean at the top in large, rounded, hand-lettered style, spelled exactly: "{story.title}". No other text, no borders.',
    ]
    return "\n".join(lines)


def _reference_lines(story: StoryText, first: int = 1) -> list[str]:
    return [f"  Reference {i} = {c.name} ({c.role}): {c.visual_description}" for i, c in enumerate(story.characters, first)]


def front_cover_prompt(story: StoryText, with_square: bool, scene: Optional[str] = None) -> str:
    """앞표지 (쪽과 같은 가로 그림, 제목 포함). with_square면 첫 참고 그림이 같은 책의 정사각형 표지다 (#88).
    scene은 정사각형이 없을 때 쓰는 장면(정책에 막혀 순화했으면 그 문장)."""
    n = len(story.characters) + (1 if with_square else 0)
    lines = [f"Wide front cover of a children's picture book. {n} reference image(s) are attached, in this order:"]
    if with_square:
        lines += ["  Reference 1 = the square cover of this same book.",
                  *_reference_lines(story, 2),
                  "Keep the square cover's scene, composition, characters and title lettering, and extend it to a wide 16:9 cover "
                  "by widening the background to the left and right. Do not crop or squeeze the characters."]
    else:
        lines += [*_reference_lines(story),
                  "The protagonist is the clear focus, warm and inviting, in a simple setting that hints at the story.",
                  f"Story setting (for mood only): {scene if scene is not None else story.pages[0].image_prompt if story.pages else ''}"]
    lines += [
        "Draw each character EXACTLY as in its reference (same species, colors, markings, proportions, outfit). Do not redesign, do not add other characters.",
        f"Style: {story.style_guide}",
        f'Put the book title in Korean at the top in large, rounded, hand-lettered style, spelled exactly: "{story.title}". No other text, no borders.',
    ]
    return "\n".join(lines)


def back_cover_prompt(story: StoryText, scene: Optional[str] = None) -> str:
    """뒤표지 (쪽과 같은 가로 그림, 글자 없음). 마지막 쪽 장면(scene, 순화했으면 그 문장)을 바탕으로 이야기를 마무리한다 (#88)."""
    lines = [f"Back cover of a children's picture book. {len(story.characters)} reference image(s) are attached, one per character, in this order:",
             *_reference_lines(story),
             "Draw each character EXACTLY as in its reference (same species, colors, markings, proportions, outfit). Do not redesign, do not add other characters.",
             f"Last scene of the story (for mood): {scene if scene is not None else story.pages[-1].image_prompt if story.pages else ''}",
             "A calm closing illustration that wraps up the story, with gentle space around the characters.",
             f"Style: {story.style_guide}",
             "No text, no title, no letters, no borders."]
    return "\n".join(lines)


def page_prompt(story: StoryText, page_chars: list[CharacterSheet], image_prompt: str, sizes: list[tuple[float, float]],
                request: Optional[str] = None, where: Optional[list[str]] = None) -> str:
    lines = [
        f"Illustrate this picture-book scene. {len(page_chars)} reference image(s) are attached, one per character, in this order:",
    ]
    for i, c in enumerate(page_chars, 1):
        lines.append(f"  Reference {i} = {c.name} ({c.role}): {c.visual_description}")
    lines += [
        "Draw each character EXACTLY as in its reference (same species, colors, markings, proportions, outfit). Do not redesign, do not swap, do not add other characters.",
        f"Scene (follow the described poses and positions precisely): {image_prompt}",
        f"Style: {story.style_guide}",
        "Time of day and light follow the Scene, not the Style: in an evening or night scene the windows are dark and lamps are on.",
        "Facial expressions follow the Scene exactly: do not turn crying, sad or angry faces into smiles.",
        "Full-bleed illustration, no text, no speech bubbles, no borders.",
    ]
    if sizes:
        lines.append(layout_prompt(sizes, where))
    if request:   # 그림만 다시의 부모 메모. 이 쪽에 맞는 부분만 반영하고 인물·화풍은 그대로
        lines.append("Parent's request for this redraw (written in Korean). Apply it where it fits this page; keep the characters, "
                     f"style and layout above unchanged. Do not draw the request as text: {request}")
    return "\n".join(lines)


def _squash(text: str) -> str:
    """공백과 강조 표시(**)를 뺀다 — 줄을 나눌 때 강조가 닫혔다 다시 열려 생긴 ****도 같게 본다."""
    return re.sub(r"\s|\*\*", "", text)


def _stale(p, pi: PageImage) -> bool:
    """이미 그린 쪽의 글 배치가 지금 글과 맞지 않나. 이전 text_blocks의 줄을 이은 글(공백 뺀)과 지금 글을 견준다.
    text_blocks가 아직 없는 옛 쪽도 다시 한다. 그림이 없는(실패한) 쪽은 배치할 게 없다."""
    if pi.status != "completed" or not pi.path:
        return False
    if not pi.text_blocks:
        return True
    old_lines = [line for b in pi.text_blocks for para in b.paragraphs for line in para]
    if _squash("".join(old_lines)) != _squash(" ".join(split_lines(p.text))):
        return True
    # 글은 같아도 줄 나누기 규칙이 바뀌었으면(대사 한 줄, #77) 덩어리·자리만 다시 한다
    return old_lines != [w for line in split_lines(p.text) for w in wrap_line(line)]


def _side(spot: Optional[dict], block: Block, i: int) -> str:
    """덩어리의 (마지막) 자리가 있던 면. 모르면 첫 덩어리는 왼쪽, 둘째는 오른쪽."""
    if spot is None:
        return "left" if i == 0 else "right"
    bw, _ = block_size(block)
    return "left" if spot["x"] / 100 * W + bw / 2 < W / 2 else "right"


def _chunk(order: int, text: str, costs: list[CostEntry]) -> list[Block]:
    """쪽 글 → 덩어리. 글 자리 계산은 생성을 막지 않는다: 어디서 실패하든 쪽의 줄을 한 덩어리로,
    그것도 안 되면 빈 목록(_arrange가 기본 자리로 처리)을 돌려준다. 글 내용은 로그에 남기지 않는다."""
    try:
        lines, blocks, cc = chunk_page(text)
        for c in cc:
            c.node = f"layout:chunk:page{order}"
        costs.extend(cc)
        if len(lines) > LINE_WARN:   # 쪽 번호와 줄 수만. 글은 남기지 않는다
            log.warning("쪽 %d: 글이 %d줄 (%d줄 초과)", order, len(lines), LINE_WARN)
        return blocks
    except Exception as e:  # noqa: BLE001
        log.warning("쪽 %d: 덩어리 나누기 계산 실패 → 한 덩어리: %s", order, type(e).__name__)
    try:
        lines = split_lines(text)
        return build_blocks(lines, [[list(range(len(lines)))]]) if lines else []
    except Exception as e:  # noqa: BLE001
        log.warning("쪽 %d: 줄 나누기도 실패 → 기본 자리: %s", order, type(e).__name__)
        return []


def _arrange(order: int, image: Optional[bytes], blocks: list[Block], costs: list[CostEntry],
             redraw: Optional[Callable[[list[Block], list[str]], Optional[bytes]]] = None) -> list[TextBlock]:
    """그림 위 글 자리. 자리 찾기 → 안 되면 한 덩어리로 합쳐 다시 → 안 되면 redraw(덩어리, where)로 다시 그린 그림에서 다시
    → 그래도 안 되면 마지막 그림에서 가장 조용한 곳(calmest) → 그림을 못 읽으면 왼쪽 면 위 기본 자리.
    늘 유효한 text_blocks를 돌려준다 (그림이 없어 읽지 못할 때도)."""
    got: Optional[list[dict]] = None
    cur: Optional[Busy] = None   # 쪽에 남는 그림(다시 그렸으면 다시 그린 것)의 복잡도
    try:
        def fit(img: bytes, busy: Busy, bl: list[Block]):
            spots, pcosts = place_page(img, bl)
            for c in pcosts:
                c.node = f"layout:place:page{order}"
            costs.extend(pcosts)
            return settle(busy, bl, spots), spots

        busy = cur = Busy(image)
        got, spots = fit(image, busy, blocks)
        merged = False
        if got is None and len(blocks) > 1:
            blocks, merged = merge(blocks), True
            got, spots = fit(image, busy, blocks)
        if got is None and redraw:
            where = ["left top"] if merged else [
                f"{_side(spots[i] if i < len(spots) else None, b, i)} top" for i, b in enumerate(blocks)]
            again = redraw(blocks, where)
            if again is not None:
                cur = None   # 쪽 그림이 바뀌었다 — 새 그림을 못 읽으면 처음 그림으로 자리를 정하지 않는다
                cur = Busy(again)
                got, spots = fit(again, cur, blocks)
    except Exception as e:  # noqa: BLE001 — 글·그림 내용은 로그에 남기지 않는다
        log.warning("쪽 %d: 글 자리 계산 실패: %s", order, type(e).__name__)
        got = None
    if got is None and cur is not None:   # 기준을 넘는 곳뿐이면 그중 가장 조용한 곳 (#71)
        try:
            got = calmest(cur, blocks)
            if got is None and len(blocks) > 1:
                blocks = merge(blocks)
                got = calmest(cur, blocks)
            if got is not None:
                log.warning("쪽 %d: 조용한 글 자리가 없어 가장 덜 복잡한 곳에 둠", order)
        except Exception as e:  # noqa: BLE001
            log.warning("쪽 %d: 가장 조용한 곳 찾기 실패: %s", order, type(e).__name__)
            got = None
    if got is None:
        log.warning("쪽 %d: 글 자리를 못 찾아 기본 자리에 둠", order)
        blocks = merge(blocks) if len(blocks) > 1 else blocks
        got = [{"x": DEFAULT_SPOT[0], "y": DEFAULT_SPOT[1], "color": DEFAULT_SPOT[2]}] * len(blocks)
    return [TextBlock(paragraphs=b, **g) for b, g in zip(blocks, got)]


def _ref(data: bytes) -> bytes:
    """첨부용 시트: 긴 변을 config.ref_max_side로 줄인 PNG. 저장된 시트는 그대로 두고, 작거나 읽지 못하면 원본 (#67).
    원본은 WebP일 수 있다. 첨부 MIME은 _attach가 실제 형식으로 붙인다 (#80)."""
    try:
        im = Image.open(io.BytesIO(data))
        if max(im.size) <= config.ref_max_side:
            return data
        im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
        im.thumbnail((config.ref_max_side, config.ref_max_side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001 — 줄이지 못해도 그리기는 이어 간다
        log.warning("첨부 시트를 줄이지 못했어요: %s", type(e).__name__)
        return data


def _run(story: StoryText, img_prefix: str, only_pages: Optional[set[int]] = None, prev: Optional[Illustrations] = None,
         request: Optional[str] = None):
    """img_prefix: 이번 실행의 그림 key 앞부분 (…/images). 일부 쪽만 다시 그리면 나머지 쪽과 시트는
    prev의 key를 그대로 둔다 — 파일을 복사하지 않는다 (API 스펙 G4).
    only_pages가 None이면 시트·표지·모든 쪽, 집합이면 그 쪽만(빈 집합이면 쪽은 그대로). 표지는 전부 그릴 때와
    제목이 바뀌었거나 이전 표지가 없을 때만 다시 그린다. request(부모 메모)는 다시 그리는 쪽 프롬프트에만 붙인다."""
    costs: list[CostEntry] = []
    ill = prev.model_copy(deep=True) if prev else Illustrations()
    by_name = {c.name: c for c in story.characters}

    # 1) 캐릭터 시트 — 일부 쪽만 다시 그릴 때는 이전 실행의 시트를 그대로 쓴다. 여러 명이면 병렬
    def make_sheet(c: CharacterSheet):
        if only_pages is not None and c.name in ill.character_sheets:
            return c.name, ill.character_sheets[c.name], None
        t0 = time.time()
        img, tin, tout = _draw(lambda desc: _gen(sheet_prompt(c.model_copy(update={"visual_description": desc}), story.style_guide)),
                               c.visual_description, f"{img_prefix} sheet {c.role}", costs)
        key = storage.write_bytes(storage.join(img_prefix, f"sheet-{c.role}-{_safe(c.name)}.{_ext(img)}"), img)
        return c.name, key, CostEntry(node=f"illustrate:sheet:{c.name}", model=config.image_model, input_tokens=tin, output_tokens=tout, images=1, ms=int((time.time() - t0) * 1000))

    with ThreadPoolExecutor(max_workers=max(1, config.image_concurrency)) as ex:
        for name, key, cost in ex.map(make_sheet, story.characters):
            ill.character_sheets[name] = key
            if cost:
                costs.append(cost)
    ref_bytes = {name: _ref(storage.read_bytes(key)) for name, key in ill.character_sheets.items()}

    # 2) 페이지 병렬 — 장면에 나오는 캐릭터 시트만 참조로
    targets = [p for p in story.pages if only_pages is None or p.order in only_pages]
    by_order = {pi.order: pi for pi in ill.pages}
    prev_pages = dict(by_order)   # 이번 실행 시작 때의 쪽들 (by_order는 결과가 나오며 바뀐다)

    redraws = 0
    redraw_lock = threading.Lock()

    def take_redraw() -> bool:
        """이번 실행에서 다시 그릴 수 있는 쪽이 남았나 (쪽들이 병렬로 돌아서 잠근다)."""
        nonlocal redraws
        with redraw_lock:
            if redraws >= MAX_REDRAWS:
                return False
            redraws += 1
            return True

    def work(p):
        t0 = time.time()
        try:
            chars = [by_name[n] for n in p.characters_in_scene if n in by_name] or [story.protagonist()]
            refs = [(f"{_safe(c.name)}.png", ref_bytes[c.name]) for c in chars]
            old_pi = prev_pages.get(p.order)   # 그림만 다시: 글이 그대로면 덩어리 나누기는 이전 그대로 (AI를 다시 부르지 않는다)
            if old_pi and old_pi.status == "completed" and old_pi.path and old_pi.text_blocks and not _stale(p, old_pi):
                blocks = [[list(para) for para in tb.paragraphs] for tb in old_pi.text_blocks]
            else:
                blocks = _chunk(p.order, p.text, costs)   # 덩어리를 먼저 나눠야 그림에 필요한 빈 곳 크기를 안다
            img, tin, tout = _draw(lambda scene: _edit(page_prompt(story, chars, scene, [block_size(b) for b in blocks], request), refs),
                                   p.image_prompt, f"{img_prefix} page {p.order}", costs)
            state = {"key": storage.write_bytes(storage.join(img_prefix, f"page-{p.order:02d}.{_ext(img)}"), img),
                     "tin": tin, "tout": tout, "images": 1}

            def redraw(bl: list[Block], where: list[str]) -> Optional[bytes]:
                if not take_redraw():
                    return None
                try:
                    again, tin2, tout2 = _draw(
                        lambda scene: _edit(page_prompt(story, chars, scene, [block_size(b) for b in bl], request, where), refs),
                        p.image_prompt, f"{img_prefix} page {p.order} redraw", costs)
                except Exception as e:  # noqa: BLE001 — 못 그리면 처음 그림 그대로 기본 자리로
                    log.warning("쪽 %d: 자리를 위한 다시 그리기 실패: %s", p.order, type(e).__name__)
                    return None
                state["key"] = storage.write_bytes(storage.join(img_prefix, f"page-{p.order:02d}.{_ext(again)}"), again)
                state["tin"] += tin2
                state["tout"] += tout2
                state["images"] += 1
                return again

            tbs = _arrange(p.order, img, blocks, costs, redraw)
            return (PageImage(order=p.order, path=state["key"], status="completed", text_blocks=tbs),
                    int((time.time() - t0) * 1000), state["tin"], state["tout"], state["images"])
        except Exception as e:  # noqa: BLE001
            return PageImage(order=p.order, status="failed", error=str(e)[:300]), int((time.time() - t0) * 1000), 0, 0, 0

    def relayout(p):
        """그림은 그대로 두고 (이전 key) 글이 바뀐 쪽의 덩어리와 자리만 다시. 다시 그리지 않는다."""
        pi = by_order[p.order]
        try:
            blocks = _chunk(p.order, p.text, costs)
            try:
                image = storage.read_bytes(pi.path)
            except Exception as e:  # noqa: BLE001
                log.warning("쪽 %d: 저장된 그림을 읽지 못함: %s", p.order, type(e).__name__)
                image = None
            return pi.model_copy(update={"text_blocks": _arrange(p.order, image, blocks, costs)})
        except Exception as e:  # noqa: BLE001 — 글 자리 계산이 전체 생성을 막지 않는다. 쪽은 이전 그대로 (글이 여전히 다르면 다음 실행에 다시 한다)
            log.warning("쪽 %d: 글 자리 다시 계산 실패 → 이전 그대로: %s", p.order, type(e).__name__)
            return pi

    sheet_refs = [(f"{_safe(c.name)}.png", ref_bytes[c.name]) for c in story.characters]
    setting = story.pages[0].image_prompt if story.pages else ""
    last_scene = story.pages[-1].image_prompt if story.pages else ""

    def draw_cover(node: str, name: str, make_prompt: Callable[[str], str], scene: str,
                   refs: list[tuple[str, bytes]], size: str) -> tuple[Optional[str], CostEntry]:
        """표지 하나. 실패하면 한 번 더 그리고, 그래도 실패하면 None (표지 때문에 실행이 실패하지 않는다, #88)."""
        t0 = time.time()
        for attempt in (1, 2):
            try:
                img, tin, tout = _draw(lambda s: _edit(make_prompt(s), refs, size=size), scene, f"{img_prefix} {name}", costs)
                key = storage.write_bytes(storage.join(img_prefix, f"{name}.{_ext(img)}"), img)
                return key, CostEntry(node=node, model=config.image_model, input_tokens=tin, output_tokens=tout,
                                      images=1, ms=int((time.time() - t0) * 1000))
            except Exception as e:  # noqa: BLE001
                log.warning("%s 실패 (%d번째): %s", name, attempt, type(e).__name__)
        return None, CostEntry(node=node, model=config.image_model, ms=int((time.time() - t0) * 1000))

    def cover():   # 정사각형 (서재 카드). 없으면 Spring이 캐릭터 시트를 쓴다
        return draw_cover("illustrate:cover", "cover", lambda scene: cover_prompt(story, scene), setting,
                          sheet_refs, config.cover_size)

    def front_cover(square_key: Optional[str]):   # 정사각형 표지를 참고해 넓힌다. 없으면 시트만
        square = None
        if square_key:
            try:
                square = _ref(storage.read_bytes(square_key))
            except Exception as e:  # noqa: BLE001
                log.warning("앞표지: 정사각형 표지를 읽지 못함: %s", type(e).__name__)
        refs = ([("square-cover.png", square)] if square else []) + sheet_refs
        return draw_cover("illustrate:front_cover", "front-cover", lambda scene: front_cover_prompt(story, square is not None, scene),
                          setting, refs, config.image_size)

    def back_cover():
        return draw_cover("illustrate:back_cover", "back-cover",
                          lambda scene: back_cover_prompt(story, scene), last_scene, sheet_refs, config.image_size)

    redraw_cover = only_pages is None or not ill.cover or ill.cover_title != story.title
    redraw_front = redraw_cover or not ill.front_cover
    last_order = story.pages[-1].order if story.pages else None
    redraw_back = only_pages is None or last_order in only_pages or not ill.back_cover
    with ThreadPoolExecutor(max_workers=max(1, config.image_concurrency)) as ex:
        cover_job = ex.submit(cover) if redraw_cover else None
        back_job = ex.submit(back_cover) if redraw_back else None
        # 앞표지는 정사각형이 끝난 뒤 (그 그림을 참고). 정사각형을 다시 그리지 않으면 이전 정사각형을 참고
        front_job = (ex.submit(lambda: front_cover(cover_job.result()[0] if cover_job else ill.cover))
                     if redraw_front else None)
        drawn = {p.order for p in targets}
        stale = [p for p in story.pages if p.order not in drawn and p.order in by_order and _stale(p, by_order[p.order])]
        relayouts = ex.map(relayout, stale)   # 글이 바뀌어 장면은 그대로인 쪽: 그림을 그대로 쓰고 배치만
        for pi, ms, tin, tout, n in ex.map(work, targets):
            by_order[pi.order] = pi
            costs.append(CostEntry(node=f"illustrate:page{pi.order}", model=config.image_model, input_tokens=tin, output_tokens=tout, images=n, ms=ms))
        for pi in relayouts:
            by_order[pi.order] = pi

        if cover_job:
            key, cost = cover_job.result()
            ill.cover, ill.cover_title = key, story.title if key else None
            costs.append(cost)
        if front_job:
            ill.front_cover, cost = front_job.result()
            costs.append(cost)
        if back_job:
            ill.back_cover, cost = back_job.result()
            costs.append(cost)

    ill.pages = [by_order[o] for o in sorted(by_order)]
    return ill, costs


def illustrate(state: PipelineState) -> dict:
    """처음 그리기·이야기 다시 만들기: 시트와 모든 쪽. 글 다시 만들기(redraw_pages가 있음): 장면이 바뀐 쪽과
    이전에 실패했거나 없던 쪽만 그리고, 나머지 쪽과 시트는 이전 실행의 key를 그대로 쓴다 (G4와 같은 방식). 글이 바뀐 쪽은 그림은 그대로 두고 덩어리·자리만 다시 한다."""
    if state.get("skip_images"):
        return {"illustrations": Illustrations(), "cost": [], "redraw_pages": None}
    story, prev, redraw = state["story"], state.get("illustrations"), state.get("redraw_pages")
    prefix = storage.join(state["output_prefix"], "images")
    if redraw is None or prev is None:
        ill, costs = _run(story, prefix)
        return {"illustrations": ill, "cost": costs, "redraw_pages": None}
    done = {pi.order for pi in prev.pages if pi.status == "completed" and pi.path}
    pages = set(redraw) | ({p.order for p in story.pages} - done)
    by_order = {pi.order: pi for pi in prev.pages}
    relayout = any(p.order in by_order and _stale(p, by_order[p.order]) for p in story.pages)
    if (not pages and not relayout and prev.cover and prev.cover_title == story.title
            and prev.front_cover and prev.back_cover):   # 글·장면·제목·표지 다 그대로 — 전부 이전 실행 것
        return {"illustrations": prev, "cost": [], "redraw_pages": None}
    ill, costs = _run(story, prefix, only_pages=pages, prev=prev)
    return {"illustrations": ill, "cost": costs, "redraw_pages": None}


_PAGE_RE = re.compile(r"((?:\d+\s*,\s*)*\d+)\s*(?:쪽|페이지)|p\s*(\d+)", re.I)


def _pages_from_feedback(fb: str) -> set[int] | None:
    """쪽·페이지·p가 붙은 숫자만 쪽 번호로 ("3쪽 다리 4개로" → {3}). 숫자만 쓴 피드백("3", "3, 5")도 쪽 번호."""
    pages = {int(n) for m in _PAGE_RE.finditer(fb) for n in re.findall(r"\d+", m.group(0))}
    pages |= {int(t) for t in fb.replace(",", " ").split() if t.isdigit()}
    return pages or None


def _memo(fb: str) -> Optional[str]:
    """쪽 번호만 쓴 피드백("3", "3, 5쪽")은 메모가 아니다."""
    fb = fb.strip()
    return fb if re.sub(r"[\d\s,]|쪽|페이지", "", fb) else None


def illustrate_only(state: PipelineState) -> dict:
    """재생성 scope=images: 그림만 다시. 쪽은 regenerate_pages(API, []면 전부), 없으면 feedback의 쪽 번호(CLI·뷰어).
    feedback(부모 메모)은 다시 그리는 쪽의 그림 프롬프트에 붙인다 (#46)."""
    fb = state.get("review_feedback") or ""
    chosen = state.get("regenerate_pages")
    pages = (set(chosen) or None) if chosen is not None else _pages_from_feedback(fb)
    ill, costs = _run(state["story"], storage.join(state["output_prefix"], "images"), only_pages=pages,
                      prev=state.get("illustrations"), request=_memo(fb))
    return {"illustrations": ill, "cost": costs}
