"""
글 덩어리 캐릭터 피하기 실험 (#104): 이미 그린 쪽 그림에 새 글 자리(_arrange, 다시 그리기는 하지 않음)를 진짜 모델로 돌려 HTML로 비교한다.

  uv run python evals/text_avoid_lab.py [--mock] [--out 이름] [--limit N] <입력>...

입력은 실행 폴더(03-story.json, 05-illustrations.json, images/)나 샘플 에셋 폴더(story.json, pages/page-NN/page-NN.webp 또는 page-NN.webp).
쪽마다 자리 찾기 호출 1번(gpt 가벼운 모델, 눈금 그림). 왼쪽 = 지금 저장된 글 자리, 오른쪽 = 새 글 자리(파란 점선 = AI가 짚은 캐릭터 칸).
다시 그리기가 필요했던 쪽은 그리지 않고 표시만 한다(그 뒤 마지막 안전판 자리를 보여 준다).
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

from firstory.nodes import illustrate as il  # noqa: E402
from firstory.nodes import layout  # noqa: E402
from firstory.nodes.layout import FONT_PATH, FONT_RATIO, H, W, SfxAsk, block_size, blockers, short_look, sound_words  # noqa: E402
from firstory.schemas import TextBlock  # noqa: E402


def load(src: Path) -> list[dict]:
    """쪽마다 {name, order, text, image(path), old(TextBlock 목록), cast}"""
    out = []
    if (src / "03-story.json").exists():
        story = json.loads((src / "03-story.json").read_text(encoding="utf-8"))
        ill = json.loads((src / "05-illustrations.json").read_text(encoding="utf-8"))
        looks = {c["name"]: short_look(c["visual_description"]) for c in story["characters"]}
        imgs = {p["order"]: p for p in ill["pages"]}
        for p in story["pages"]:
            pi = imgs.get(p["order"]) or {}
            if not pi.get("path") or not pi.get("text_blocks"):
                continue
            out.append({"name": src.name, "order": p["order"], "text": p["text"], "image": src.parent / pi["path"],
                        "old": [TextBlock(**b) for b in pi["text_blocks"]],
                        "cast": [(n, looks.get(n, "")) for n in p["characters_in_scene"]]})
    else:
        story = json.loads((src / "story.json").read_text(encoding="utf-8"))
        for p in story["pages"]:
            n = p["pageNo"]
            old = [TextBlock(paragraphs=b["paragraphs"], x=b["x"], y=b["y"], color=b["color"].lower()) for b in p.get("textBlocks") or []]
            if not old:
                continue
            nested = src / "pages" / f"page-{n:02d}" / f"page-{n:02d}.webp"
            flat = src / (p.get("image") or f"page-{n:02d}.webp")
            out.append({"name": story.get("title", src.name), "order": n, "text": p["text"],
                        "image": nested if nested.exists() else flat, "old": old, "cast": []})
    return out


def blocks_html(tbs: list[TextBlock]) -> str:
    out = []
    for b in tbs:
        paras = "".join(f'<p>{"<br>".join(html.escape(l).replace("**", "") for l in para)}</p>' for para in b.paragraphs)
        out.append(f'<div class="tb {b.color}" style="left:{b.x}%;top:{b.y}%">{paras}</div>')
    return "".join(out)


def overlap(tbs: list[TextBlock], chars) -> float:
    """덩어리들이 (넉넉히 키운) 캐릭터 칸과 겹친 넓이, 그림 넓이 대비 %"""
    av = blockers(chars)
    return sum(layout._overlap(t.x / 100 * W, t.y / 100 * H, *block_size(t.paragraphs), av) for t in tbs) / (W * H) * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", default="text-avoid-1116")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mock", action="store_true", help="가짜 AI로 (호출·비용 0). FIRSTORY_MOCK은 서버에서만 먹는다")
    args = ap.parse_args()
    if args.mock:
        from firstory import llm, mock
        llm.set_structured_override(mock.fake_structured)

    out_dir = ROOT / "out" / args.out
    (out_dir / "img").mkdir(parents=True, exist_ok=True)
    shutil.copy(FONT_PATH, out_dir / "font.woff2")
    pages = [pg for src in args.inputs for pg in load(Path(src).expanduser().resolve())]
    if args.limit:
        pages = pages[:args.limit]

    # 쪽마다 AI가 짚은 칸을 보려고 place_page를 감싼다 (그림 하나에 첫 답)
    seen: list = []
    orig_place = il.place_page

    def spy(*a, **k):
        r = orig_place(*a, **k)
        seen.append(r[1])
        return r

    il.place_page = spy
    rows, tin, tout = [], 0, 0
    stats = {"before": 0, "after": 0, "split": 0, "redraw": 0, "nochars": 0}
    for i, pg in enumerate(pages):
        image = pg["image"].read_bytes()
        words = sound_words(pg["text"])
        sfx = SfxAsk(word=words[0], text=pg["text"], cast=pg["cast"]) if words else None
        blocks = [b.paragraphs for b in pg["old"]]
        seen.clear()
        wanted: list = []
        costs: list = []
        t0 = time.time()
        new, sw = il._arrange(pg["order"], image, blocks, costs, lambda bl, where: wanted.append(where) or None, sfx)
        ms = int((time.time() - t0) * 1000)
        tin += sum(c.input_tokens for c in costs)
        tout += sum(c.output_tokens for c in costs)
        chars = seen[0] if seen else []
        ob, oa = overlap(pg["old"], chars), overlap(new, chars)
        stats["before"] += ob > 0
        stats["after"] += oa > 0
        stats["split"] += len(new) > len(pg["old"])
        stats["redraw"] += bool(wanted)
        stats["nochars"] += not chars
        name = f"img/{i:02d}{pg['image'].suffix}"
        shutil.copy(pg["image"], out_dir / name)
        cbox = "".join(f'<span class="cbox" style="left:{b[0]}%;top:{b[1]}%;width:{b[2] - b[0]}%;height:{b[3] - b[1]}%"></span>'
                       for _, b in chars)
        word_html = "".join(f'<span class="sw" style="left:{q.x}%;top:{q.y}%;color:{sw.color}">{html.escape(q.text)}</span>'
                            for q in sw.pieces) if sw else ""
        meta = (f"<b>{html.escape(pg['name'])} {pg['order']}쪽</b> · 캐릭터 칸 {len(chars)}개"
                f" · 겹침 {ob:.1f}% → {oa:.1f}% · 덩어리 {len(pg['old'])} → {len(new)}"
                f"{' · <b>다시 그리기 필요</b>' if wanted else ''} · {ms / 1000:.1f}초"
                f" · 입력 {sum(c.input_tokens for c in costs)} / 출력 {sum(c.output_tokens for c in costs)}토큰")
        rows.append(f"""
<section><div class="meta">{meta}</div>
<div class="pair">
  <figure><div class="pg"><img src="{name}">{blocks_html(pg['old'])}{cbox}</div><figcaption>지금 저장된 글 자리 (파란 점선은 새로 받은 캐릭터 칸)</figcaption></figure>
  <figure><div class="pg"><img src="{name}">{blocks_html(new)}{word_html}{cbox}</div><figcaption>새 글 자리{' + 의성어' if sfx else ''}</figcaption></figure>
</div></section>""")
        print(f"{i + 1}/{len(pages)} {pg['order']}쪽 {ms}ms 겹침 {ob:.1f}→{oa:.1f}", flush=True)
    il.place_page = orig_place

    head = f"""<!doctype html><meta charset="utf-8"><title>글 캐릭터 피하기 실험</title>
<style>
@font-face{{font-family:K;src:url(font.woff2)}}
body{{font-family:-apple-system,sans-serif;margin:16px;background:#f6f5f2;color:#222}}
section{{margin:0 0 28px}} .meta{{font-size:14px;margin:4px 0 8px}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} figure{{margin:0}} figcaption{{font-size:12px;color:#666;margin-top:4px}}
.pg{{position:relative;container-type:inline-size;aspect-ratio:{W}/{H}}} .pg img{{width:100%;height:100%;object-fit:cover;display:block}}
.tb{{position:absolute;font-family:K;font-size:{FONT_RATIO * 100:g}cqw;line-height:1.55;white-space:nowrap}} .tb p{{margin:0 0 .93em}}
.tb.dark{{color:#4a4a4a}} .tb.light{{color:#fff}}
.sw{{position:absolute;transform:translate(-50%,-50%);font-family:K;font-weight:700;font-size:{layout.PIECE_RATIO * 100:g}cqw;white-space:nowrap}}
.cbox{{position:absolute;border:1.5px dashed rgba(0,120,255,.7);box-sizing:border-box}}
</style>
<h1>글 캐릭터 피하기 실험 (#104)</h1>
<p>{len(pages)}쪽 · 입력 {tin} / 출력 {tout}토큰 · 캐릭터와 겹친 쪽 {stats['before']} → {stats['after']} · 나눈 쪽 {stats['split']}
 · 다시 그리기 필요 {stats['redraw']} · 칸 못 받은 쪽 {stats['nochars']}</p>"""
    (out_dir / "index.html").write_text(head + "".join(rows), encoding="utf-8")
    print(out_dir / "index.html", f"tokens in={tin} out={tout}", stats)


if __name__ == "__main__":
    main()
