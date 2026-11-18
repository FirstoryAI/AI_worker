"""
글 자리 실험(text_avoid_lab, sound_word_lab)이 같이 쓰는 쪽 읽기·HTML 조각. API 호출 없음.
src를 sys.path에 넣은 뒤 가져온다.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from firstory.nodes.layout import short_look, sound_words
from firstory.schemas import TextBlock


def load_pages(src: Path, *, sound_only: bool = False, sample_cast: list | None = None) -> list[dict]:
    """쪽마다 {name, order, text, image(path), old(TextBlock 목록), cast}. 글 자리(text_blocks)가 없는 쪽은 뺀다.
    src는 실행 폴더(03-story.json, 05-illustrations.json, images/)나 샘플 에셋 폴더(story.json + 쪽 그림).
    sound_only: 별표 말이 있는 쪽만. sample_cast: 샘플 에셋 중 노란접시 모양(pages/page-NN/)일 때 쓸 인물"""
    out = []
    if (src / "03-story.json").exists():
        story = json.loads((src / "03-story.json").read_text(encoding="utf-8"))
        ill = json.loads((src / "05-illustrations.json").read_text(encoding="utf-8"))
        looks = {c["name"]: short_look(c["visual_description"]) for c in story["characters"]}
        imgs = {p["order"]: p for p in ill["pages"]}
        for p in story["pages"]:
            pi = imgs.get(p["order"]) or {}
            if (sound_only and not sound_words(p["text"])) or not pi.get("path") or not pi.get("text_blocks"):
                continue
            out.append({"name": src.name, "order": p["order"], "text": p["text"], "image": src.parent / pi["path"],
                        "old": [TextBlock(**b) for b in pi["text_blocks"]],
                        "cast": [(n, looks.get(n, "")) for n in p["characters_in_scene"]]})
    else:
        story = json.loads((src / "story.json").read_text(encoding="utf-8"))
        for p in story["pages"]:
            if sound_only and not sound_words(p["text"]):
                continue
            n = p["pageNo"]
            old = [TextBlock(paragraphs=b["paragraphs"], x=b["x"], y=b["y"], color=b["color"].lower()) for b in p.get("textBlocks") or []]
            if not old:
                continue
            nested = src / "pages" / f"page-{n:02d}" / f"page-{n:02d}.webp"   # 노란접시 에셋 모양
            flat = src / (p.get("image") or f"page-{n:02d}.webp")              # 프론트 sample-stories 모양 (인물 정보 없음)
            out.append({"name": story.get("title", src.name), "order": n, "text": p["text"],
                        "image": nested if nested.exists() else flat, "old": old,
                        "cast": (sample_cast or []) if nested.exists() else []})
    return out


def blocks_html(tbs: list[TextBlock]) -> str:
    out = []
    for b in tbs:
        paras = "".join(f'<p>{"<br>".join(html.escape(l).replace("**", "") for l in para)}</p>' for para in b.paragraphs)
        out.append(f'<div class="tb {b.color}" style="left:{b.x}%;top:{b.y}%">{paras}</div>')
    return "".join(out)


def word_html(sw) -> str:
    """의성어 조각(SoundWord | None)을 서버가 고른 색으로"""
    if not sw:
        return ""
    return "".join(f'<span class="sw" style="left:{q.x}%;top:{q.y}%;color:{sw.color}">{html.escape(q.text)}</span>'
                   for q in sw.pieces)
