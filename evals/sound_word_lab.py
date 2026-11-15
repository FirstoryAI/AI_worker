"""
의성어 자리 실험 (#92): 이미 그린 쪽 그림에 새 자리 찾기(글 덩어리 + 의성어)를 진짜 모델로 돌려 HTML로 비교한다.

  uv run python evals/sound_word_lab.py [--grid] [--out 이름] <입력>...

입력은 실행 폴더(03-story.json, 05-illustrations.json, images/)나 샘플 에셋 폴더(story.json, pages/page-NN/page-NN.webp).
별표 말이 있는 쪽만 부른다. 왼쪽 = 지금 저장된 글 자리, 오른쪽 = 새 글 자리 + 의성어(빨간 점 = AI가 처음 짚은 점).
--grid: 자리 찾기 그림에 10% 눈금을 그려 보낸다.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstory.nodes.layout import (  # noqa: E402
    FONT_PATH, H, W, Busy, SfxAsk, place_page, settle, settle_word, short_look, sound_words,
)
from firstory.schemas import TextBlock  # noqa: E402

SAMPLE_CAST = [("미루", "A small white rabbit, the main character"), ("가온 선생님", "A big brown bear teacher")]


def load(src: Path) -> list[dict]:
    """쪽마다 {name, order, text, image(path), blocks(지금 text_blocks 문단), old(TextBlock 목록), cast}"""
    out = []
    if (src / "03-story.json").exists():
        story = json.loads((src / "03-story.json").read_text(encoding="utf-8"))
        ill = json.loads((src / "05-illustrations.json").read_text(encoding="utf-8"))
        looks = {c["name"]: short_look(c["visual_description"]) for c in story["characters"]}
        imgs = {p["order"]: p for p in ill["pages"]}
        for p in story["pages"]:
            pi = imgs.get(p["order"]) or {}
            if not sound_words(p["text"]) or not pi.get("path") or not pi.get("text_blocks"):
                continue
            old = [TextBlock(**b) for b in pi["text_blocks"]]
            out.append({"name": src.name, "order": p["order"], "text": p["text"],
                        "image": src.parent / pi["path"], "old": old,
                        "cast": [(n, looks.get(n, "")) for n in p["characters_in_scene"]]})
    else:
        story = json.loads((src / "story.json").read_text(encoding="utf-8"))
        for p in story["pages"]:
            if not sound_words(p["text"]):
                continue
            n = p["pageNo"]
            old = [TextBlock(paragraphs=b["paragraphs"], x=b["x"], y=b["y"], color=b["color"].lower()) for b in p.get("textBlocks") or []]
            if not old:
                continue
            out.append({"name": story.get("title", src.name), "order": n, "text": p["text"],
                        "image": src / "pages" / f"page-{n:02d}" / f"page-{n:02d}.webp", "old": old, "cast": SAMPLE_CAST})
    return out


def blocks_html(tbs: list[TextBlock]) -> str:
    out = []
    for b in tbs:
        paras = "".join(f'<p>{"<br>".join(html.escape(l).replace("**", "") for l in para)}</p>' for para in b.paragraphs)
        out.append(f'<div class="tb {b.color}" style="left:{b.x}%;top:{b.y}%">{paras}</div>')
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--out", default="sound-word-lab-1115")
    args = ap.parse_args()

    out_dir = ROOT / "out" / (args.out + ("-grid" if args.grid else ""))
    (out_dir / "img").mkdir(parents=True, exist_ok=True)
    shutil.copy(FONT_PATH, out_dir / "font.woff2")

    pages = [pg for src in args.inputs for pg in load(Path(src).expanduser().resolve())]
    rows, tin, tout = [], 0, 0
    for i, pg in enumerate(pages):
        image = pg["image"].read_bytes()
        busy = Busy(image)
        word = sound_words(pg["text"])[0]
        ask = SfxAsk(word=word, text=pg["text"], cast=pg["cast"])
        blocks = [b.paragraphs for b in pg["old"]]
        t0 = time.time()
        spots, wspot, costs = place_page(image, blocks, ask, grid=args.grid)
        ms = int((time.time() - t0) * 1000)
        tin += sum(c.input_tokens for c in costs)
        tout += sum(c.output_tokens for c in costs)
        got = settle(busy, blocks, spots) if spots else None
        new = [TextBlock(paragraphs=b, **g) for b, g in zip(blocks, got)] if got else []
        sw = settle_word(busy, word, wspot, new or pg["old"])
        name = f"img/{i:02d}{pg['image'].suffix}"
        shutil.copy(pg["image"], out_dir / name)
        dot = (f'<span class="dot" style="left:{wspot["x"]}%;top:{wspot["y"]}%"></span>' if wspot else "")
        bx = wspot.get("box") if wspot else None
        if bx:
            dot += f'<span class="box" style="left:{bx[0]}%;top:{bx[1]}%;width:{bx[2] - bx[0]}%;height:{bx[3] - bx[1]}%"></span>'

        word_html = (f'<span class="sw {sw.color}" style="left:{sw.x}%;top:{sw.y}%">{html.escape(sw.text)}</span>' if sw else "")
        moved = (f"밀림 ({wspot['x']:.1f}, {wspot['y']:.1f}) → ({sw.x}, {sw.y})" if sw and wspot and (abs(sw.x - wspot["x"]) > 0.05 or abs(sw.y - wspot["y"]) > 0.05)
                 else ("AI 자리 그대로" if sw else "놓을 곳 없음 → null" if wspot else "AI 답 없음 → null"))
        meta = (f"<b>{html.escape(pg['name'])} {pg['order']}쪽</b> · 말 <b>{html.escape(word)}</b> · AI가 고른 주인 <b>{html.escape((wspot or {}).get('owner', '-'))}</b>"
                f" · {moved} · 글 자리 {'새 자리' if new else '못 정함(기존 자리로 그림)'} · {ms / 1000:.1f}초"
                f" · 입력 {sum(c.input_tokens for c in costs)} / 출력 {sum(c.output_tokens for c in costs)}토큰")
        rows.append(f"""
<section><div class="meta">{meta}</div>
<div class="pair">
  <figure><div class="pg"><img src="{name}">{blocks_html(pg['old'])}</div><figcaption>지금 저장된 글 자리</figcaption></figure>
  <figure><div class="pg"><img src="{name}">{blocks_html(new or pg['old'])}{word_html}{dot}</div><figcaption>새 글 자리 + 의성어{' (눈금 그림으로 물음)' if args.grid else ''}</figcaption></figure>
</div>
<details><summary>본문</summary><pre>{html.escape(pg['text'])}</pre></details></section>""")
        print(f"{i + 1}/{len(pages)} {pg['order']}쪽 {ms}ms", flush=True)

    head = f"""<!doctype html><meta charset="utf-8"><title>의성어 자리 실험</title>
<style>
@font-face{{font-family:K;src:url(font.woff2)}}
body{{font-family:-apple-system,sans-serif;margin:16px;background:#f6f5f2;color:#222}}
section{{margin:0 0 28px}} .meta{{font-size:14px;margin:4px 0 8px}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} figure{{margin:0}} figcaption{{font-size:12px;color:#666;margin-top:4px}}
.pg{{position:relative;container-type:inline-size;aspect-ratio:{W}/{H}}} .pg img{{width:100%;height:100%;object-fit:cover;display:block}}
.tb{{position:absolute;font-family:K;font-size:1.5cqw;line-height:1.55;white-space:nowrap}} .tb p{{margin:0 0 .93em}}
.tb.dark{{color:#4a4a4a}} .tb.light{{color:#fff}}
.sw{{position:absolute;transform:translate(-50%,-50%);font-family:K;font-weight:700;font-size:3.5cqw;line-height:1.2;white-space:nowrap}}
.sw.dark{{color:#4a4a4a;text-shadow:0 0 .12em #fff,0 0 .12em #fff}} .sw.light{{color:#fff;text-shadow:0 0 .12em #333,0 0 .12em #333}}
.box{{position:absolute;border:2px dashed rgba(0,120,255,.8);box-sizing:border-box}}
.dot{{position:absolute;width:10px;height:10px;margin:-5px 0 0 -5px;border-radius:50%;border:2px solid red;box-sizing:border-box;opacity:.8}}
pre{{white-space:pre-wrap;font-size:13px}}
</style>
<h1>의성어 자리 실험 (#92){' — 눈금' if args.grid else ''}</h1>
<p>{len(pages)}쪽 · 입력 {tin} / 출력 {tout}토큰. 빨간 고리 = AI가 처음 짚은 말 가운데, 파란 점선 = AI가 짚은 주인 칸, 글자 = 코드 검사 뒤 최종 자리. 말 글자 크기는 그림 폭 3.5%.</p>"""
    (out_dir / "index.html").write_text(head + "".join(rows), encoding="utf-8")
    print(out_dir / "index.html", f"tokens in={tin} out={tout}")


if __name__ == "__main__":
    main()
