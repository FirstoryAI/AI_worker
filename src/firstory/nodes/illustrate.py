"""
🔒 ④ 일러스트: 캐릭터 시트(주인공 + 조연) 각 1장 → 페이지마다 그 장면에 나오는 캐릭터의 시트만 참조로 넣고 병렬 생성.
자동 재시도 없음 — 실패한 페이지는 failed 로 두고, 뷰어 [재시도]로 그 페이지만.
"""
from __future__ import annotations

import base64
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from ..config import config
from ..llm import client
from ..schemas import CharacterSheet, CostEntry, Illustrations, PageImage, StoryText
from ..state import PipelineState

# 테스트용 훅: (prompt, [ref_png...]) -> png bytes
_override: Optional[Callable[[str, list[bytes]], bytes]] = None


def set_image_override(fn):
    global _override
    _override = fn


def _usage(res) -> tuple[int, int]:
    u = getattr(res, "usage", None)
    return (getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0) if u else (0, 0)


def _gen(prompt_text: str) -> tuple[bytes, int, int]:
    """→ (png, input_tokens, output_tokens). 이미지 비용은 토큰으로 매겨진다."""
    if _override:
        return _override(prompt_text, []), 0, 0
    res = client().images.generate(
        model=config.image_model, prompt=prompt_text, size=config.image_size, quality=config.image_quality, n=1
    )
    return base64.b64decode(res.data[0].b64_json), *_usage(res)


def _edit(prompt_text: str, refs: list[tuple[str, bytes]]) -> tuple[bytes, int, int]:
    """refs: [(파일명, png bytes)]. 여러 장이면 리스트로 넘긴다 (gpt-image-2는 참조 이미지 여러 장 지원)."""
    if _override:
        return _override(prompt_text, [b for _, b in refs]), 0, 0
    images = [(name, data, "image/png") for name, data in refs]
    res = client().images.edit(
        model=config.image_model,
        image=images if len(images) > 1 else images[0],
        prompt=prompt_text,
        size=config.image_size,
        quality=config.image_quality,
        n=1,
        **({"input_fidelity": "high"} if config.image_model.startswith("gpt-image-1") else {}),  # 1/1.5 전용
    )
    return base64.b64decode(res.data[0].b64_json), *_usage(res)


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name)


def sheet_prompt(c: CharacterSheet, style: str) -> str:
    return "\n".join([
        "Character reference sheet for a children's picture book. Single character, full body, neutral standing pose, facing slightly left, plain cream background.",
        f"Character: {c.visual_description}",
        f"Style: {style}",
        "No text, no labels, no multiple poses — one clean full-body view.",
    ])


def page_prompt(story: StoryText, page_chars: list[CharacterSheet], image_prompt: str) -> str:
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
    ]
    return "\n".join(lines)


def _run(story: StoryText, img_dir: Path, only_pages: Optional[set[int]] = None, prev: Optional[Illustrations] = None):
    img_dir.mkdir(parents=True, exist_ok=True)
    costs: list[CostEntry] = []
    ill = prev.model_copy(deep=True) if prev else Illustrations()
    by_name = {c.name: c for c in story.characters}

    # 1) 캐릭터 시트 — 없는 것만 (일부 페이지 재생성 때는 재사용). 여러 명이면 병렬
    def make_sheet(c: CharacterSheet):
        path = img_dir / f"sheet-{c.role}-{_safe(c.name)}.png"
        if only_pages and path.exists():
            return c.name, path, None
        t0 = time.time()
        png, tin, tout = _gen(sheet_prompt(c, story.style_guide))
        path.write_bytes(png)
        return c.name, path, CostEntry(node=f"illustrate:sheet:{c.name}", model=config.image_model, input_tokens=tin, output_tokens=tout, images=1, ms=int((time.time() - t0) * 1000))

    with ThreadPoolExecutor(max_workers=max(1, config.image_concurrency)) as ex:
        for name, path, cost in ex.map(make_sheet, story.characters):
            ill.character_sheets[name] = str(path)
            if cost:
                costs.append(cost)
    ref_bytes = {name: Path(p).read_bytes() for name, p in ill.character_sheets.items()}

    # 2) 페이지 병렬 — 장면에 나오는 캐릭터 시트만 참조로
    targets = [p for p in story.pages if not only_pages or p.order in only_pages]
    by_order = {pi.order: pi for pi in ill.pages}

    def work(p):
        path = img_dir / f"page-{p.order:02d}.png"
        t0 = time.time()
        try:
            chars = [by_name[n] for n in p.characters_in_scene if n in by_name] or [story.protagonist()]
            refs = [(f"{_safe(c.name)}.png", ref_bytes[c.name]) for c in chars]
            png, tin, tout = _edit(page_prompt(story, chars, p.image_prompt), refs)
            path.write_bytes(png)
            return PageImage(order=p.order, path=str(path), status="completed"), int((time.time() - t0) * 1000), tin, tout
        except Exception as e:  # noqa: BLE001
            return PageImage(order=p.order, status="failed", error=str(e)[:300]), int((time.time() - t0) * 1000), 0, 0

    with ThreadPoolExecutor(max_workers=max(1, config.image_concurrency)) as ex:
        for pi, ms, tin, tout in ex.map(work, targets):
            by_order[pi.order] = pi
            costs.append(CostEntry(node=f"illustrate:page{pi.order}", model=config.image_model, input_tokens=tin, output_tokens=tout, images=1 if pi.status == "completed" else 0, ms=ms))

    ill.pages = [by_order[o] for o in sorted(by_order)]
    return ill, costs


def illustrate(state: PipelineState) -> dict:
    if state.get("skip_images"):
        return {"illustrations": Illustrations(), "cost": []}
    ill, costs = _run(state["story"], Path(state["run_dir"]) / "images")
    return {"illustrations": ill, "cost": costs}


def illustrate_only(state: PipelineState) -> dict:
    """재생성 scope=images: 그림만 다시 (feedback에 페이지 번호가 있으면 그 페이지만)."""
    fb = state.get("review_feedback") or ""
    pages = {int(t) for t in re.findall(r"\d+", fb)} or None  # "3페이지", "3, 5쪽", "p3"
    ill, costs = _run(state["story"], Path(state["run_dir"]) / "images", only_pages=pages, prev=state.get("illustrations"))
    return {"illustrations": ill, "cost": costs}
