"""
🔒 ④ 일러스트: 캐릭터 시트(주인공 + 조연) 각 1장 → 페이지마다 그 장면에 나오는 캐릭터의 시트만 참조로 넣고 병렬 생성.
자동 재시도는 콘텐츠 정책에 막혔을 때만 한 번 — 장면 설명을 순화해서 다시 그린다 (#37).
그래도 실패한 페이지는 failed 로 두고, 뷰어 [재시도]로 그 페이지만.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from .. import storage
from ..config import config
from openai import BadRequestError

from ..llm import client, prompt, structured
from ..schemas import CharacterSheet, CostEntry, Illustrations, PageImage, SoftenedScene, StoryText
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


def _gen(prompt_text: str) -> tuple[bytes, int, int]:
    """→ (png, input_tokens, output_tokens). 이미지 비용은 토큰으로 매겨진다."""
    if _override:
        return _override(prompt_text, []), 0, 0
    try:
        res = client().images.generate(
            model=config.image_model, prompt=prompt_text, size=config.image_size, quality=config.image_quality, n=1
        )
    except BadRequestError as e:
        raise _policy(e) from e
    return base64.b64decode(res.data[0].b64_json), *_usage(res)


def _edit(prompt_text: str, refs: list[tuple[str, bytes]], size: Optional[str] = None) -> tuple[bytes, int, int]:
    """refs: [(파일명, png bytes)]. 여러 장이면 리스트로 넘긴다 (gpt-image-2는 참조 이미지 여러 장 지원).
    쪽·표지라 config.image_format으로 받는다 (#32). 저장 key 확장자는 _ext로 실제 바이트를 보고 정한다."""
    if _override:
        return _override(prompt_text, [b for _, b in refs]), 0, 0
    images = [(name, data, "image/png") for name, data in refs]
    try:
        res = client().images.edit(
            model=config.image_model,
            image=images if len(images) > 1 else images[0],
            prompt=prompt_text,
            size=size or config.image_size,
            quality=config.image_quality,
            n=1,
            **({"input_fidelity": "high"} if config.image_model.startswith("gpt-image-1") else {}),  # 1/1.5 전용
            **({"output_format": config.image_format, "output_compression": config.image_compression}
               if config.image_format != "png" else {}),
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


_LAYOUT = {
    "bottom": "Layout: keep the bottom 30% of the image as a calm, empty area for the story text to be placed later — "
              "only a soft, plain continuation of the floor or ground with very little detail. "
              "Place all characters, faces and important objects in the upper 70%. Nothing important may touch the bottom 30%.",
    "top": "Layout: keep the top 30% of the image as a calm, empty area for the story text to be placed later — "
           "only a soft, plain continuation of the wall, ceiling or sky with very little detail. "
           "Place all characters, faces and important objects in the lower 70%. Nothing important may touch the top 30%.",
}


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


def page_prompt(story: StoryText, page_chars: list[CharacterSheet], image_prompt: str, text_position: str = "bottom",
                request: Optional[str] = None) -> str:
    lines = [
        f"Illustrate this picture-book scene. {len(page_chars)} reference image(s) are attached, one per character, in this order:",
    ]
    for i, c in enumerate(page_chars, 1):
        lines.append(f"  Reference {i} = {c.name} ({c.role}): {c.visual_description}")
    lines += [
        "Draw each character EXACTLY as in its reference (same species, colors, markings, proportions, outfit). Do not redesign, do not swap, do not add other characters.",
        f"Scene (follow the described poses and positions precisely): {image_prompt}",
        f"Style: {story.style_guide}",
        "Full-bleed illustration, no text, no speech bubbles, no borders.",
        _LAYOUT[text_position],
    ]
    if request:   # 그림만 다시의 부모 메모. 이 쪽에 맞는 부분만 반영하고 인물·화풍은 그대로
        lines.append("Parent's request for this redraw (written in Korean). Apply it where it fits this page; keep the characters, "
                     f"style and layout above unchanged. Do not draw the request as text: {request}")
    return "\n".join(lines)


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
        png, tin, tout = _draw(lambda desc: _gen(sheet_prompt(c.model_copy(update={"visual_description": desc}), story.style_guide)),
                               c.visual_description, f"{img_prefix} sheet {c.role}", costs)
        key = storage.write_bytes(storage.join(img_prefix, f"sheet-{c.role}-{_safe(c.name)}.png"), png)
        return c.name, key, CostEntry(node=f"illustrate:sheet:{c.name}", model=config.image_model, input_tokens=tin, output_tokens=tout, images=1, ms=int((time.time() - t0) * 1000))

    with ThreadPoolExecutor(max_workers=max(1, config.image_concurrency)) as ex:
        for name, key, cost in ex.map(make_sheet, story.characters):
            ill.character_sheets[name] = key
            if cost:
                costs.append(cost)
    ref_bytes = {name: storage.read_bytes(key) for name, key in ill.character_sheets.items()}

    # 2) 페이지 병렬 — 장면에 나오는 캐릭터 시트만 참조로
    targets = [p for p in story.pages if only_pages is None or p.order in only_pages]
    by_order = {pi.order: pi for pi in ill.pages}

    def work(p):
        t0 = time.time()
        try:
            chars = [by_name[n] for n in p.characters_in_scene if n in by_name] or [story.protagonist()]
            refs = [(f"{_safe(c.name)}.png", ref_bytes[c.name]) for c in chars]
            img, tin, tout = _draw(lambda scene: _edit(page_prompt(story, chars, scene, p.text_position, request), refs),
                                   p.image_prompt, f"{img_prefix} page {p.order}", costs)
            key = storage.write_bytes(storage.join(img_prefix, f"page-{p.order:02d}.{_ext(img)}"), img)
            return PageImage(order=p.order, path=key, status="completed"), int((time.time() - t0) * 1000), tin, tout
        except Exception as e:  # noqa: BLE001
            return PageImage(order=p.order, status="failed", error=str(e)[:300]), int((time.time() - t0) * 1000), 0, 0

    def cover():
        t0 = time.time()
        try:
            refs = [(f"{_safe(c.name)}.png", ref_bytes[c.name]) for c in story.characters]
            setting = story.pages[0].image_prompt if story.pages else ""
            img, tin, tout = _draw(lambda scene: _edit(cover_prompt(story, scene), refs, size=config.cover_size),
                                   setting, f"{img_prefix} cover", costs)
            key = storage.write_bytes(storage.join(img_prefix, f"cover.{_ext(img)}"), img)
            return key, CostEntry(node="illustrate:cover", model=config.image_model, input_tokens=tin, output_tokens=tout, images=1, ms=int((time.time() - t0) * 1000))
        except Exception:  # noqa: BLE001 — 표지가 없으면 Spring이 캐릭터 시트를 쓴다
            return None, CostEntry(node="illustrate:cover", model=config.image_model, ms=int((time.time() - t0) * 1000))

    redraw_cover = only_pages is None or not ill.cover or ill.cover_title != story.title
    with ThreadPoolExecutor(max_workers=max(1, config.image_concurrency)) as ex:
        cover_job = ex.submit(cover) if redraw_cover else None
        for pi, ms, tin, tout in ex.map(work, targets):
            by_order[pi.order] = pi
            costs.append(CostEntry(node=f"illustrate:page{pi.order}", model=config.image_model, input_tokens=tin, output_tokens=tout, images=1 if pi.status == "completed" else 0, ms=ms))

        if cover_job:
            key, cost = cover_job.result()
            ill.cover, ill.cover_title = key, story.title if key else None
            costs.append(cost)

    ill.pages = [by_order[o] for o in sorted(by_order)]
    return ill, costs


def illustrate(state: PipelineState) -> dict:
    """처음 그리기·이야기 다시 만들기: 시트와 모든 쪽. 글 다시 만들기(redraw_pages가 있음): 장면이 바뀐 쪽과
    이전에 실패했거나 없던 쪽만 그리고, 나머지 쪽과 시트는 이전 실행의 key를 그대로 쓴다 (G4와 같은 방식)."""
    if state.get("skip_images"):
        return {"illustrations": Illustrations(), "cost": [], "redraw_pages": None}
    story, prev, redraw = state["story"], state.get("illustrations"), state.get("redraw_pages")
    prefix = storage.join(state["output_prefix"], "images")
    if redraw is None or prev is None:
        ill, costs = _run(story, prefix)
        return {"illustrations": ill, "cost": costs, "redraw_pages": None}
    done = {pi.order for pi in prev.pages if pi.status == "completed" and pi.path}
    pages = set(redraw) | ({p.order for p in story.pages} - done)
    if not pages and prev.cover and prev.cover_title == story.title:   # 글만 바뀌고 장면·제목은 그대로 — 그림은 전부 이전 실행 것
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
