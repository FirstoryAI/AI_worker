"""
홈 샘플 동화 8편의 글 자리·의성어를 지금 파이프라인 기준으로 다시 잡는다 (Backend#45, 설계 docs/superpowers/specs/2026-11-17-sample-stories-refresh-design.md).

  uv run python evals/sample_refresh.py place [--mock] [--limit N] [--cards tantrum,friend]
      쪽마다 자리 찾기 1번(다시 그리지 않음) → out/sample-refresh-1117/result.json, index.html (미리보기)
  uv run python evals/sample_refresh.py redraw --pages tantrum:3,friend:7 [--mock]
      고른 쪽만 지금 그림을 참고로 글 자리를 비워 다시 그리고 다시 배치
  uv run python evals/sample_refresh.py revert --pages tantrum:3
      다시 그린 쪽을 옛 그림·옛 결과로 되돌림
  uv run python evals/sample_refresh.py export
      샘플동화-1106/ 으로 원본 보관(없을 때만) → 샘플동화/<카드>/story.json·그림 갱신 → 샘플동화_1117.zip

원본 글·그림은 ~/Desktop/FIRSTORY/샘플동화/ (export 전까지 읽기만). 로그에 동화 글을 남기지 않는다.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstory.nodes import illustrate as il  # noqa: E402
from firstory.nodes import layout  # noqa: E402
from firstory.nodes.layout import FONT_PATH, FONT_RATIO, H, PIECE_RATIO, W, SfxAsk, sound_words, wrap_line  # noqa: E402
from firstory.schemas import SoundWord, TextBlock  # noqa: E402

FIRSTORY = ROOT.parent
SAMPLES = FIRSTORY / "샘플동화"
OUT = ROOT / "out" / "sample-refresh-1117"
RESULT = OUT / "result.json"

Paras = list[list[list[str]]]   # 덩어리 > 문단 > 줄


# ── 순수 함수 ──
def rewrap(blocks: Paras) -> Paras:
    """지금 글자 크기(2.35%)로 줄마다 다시 감는다. 옛 샘플 줄은 모두 문장 단위라 잇지 않는다."""
    return [[[w for line in para for w in wrap_line(line)] for para in b] for b in blocks]


def _flat(blocks: Paras) -> str:
    return re.sub(r"\s|\*\*", "", "".join(line for b in blocks for para in b for line in para))


def same_text(a: Paras, b: Paras) -> bool:
    """공백·강조 표시(**)를 빼고 이은 글이 같은지"""
    return _flat(a) == _flat(b)


def to_front(tbs: list[TextBlock], sw: SoundWord | None) -> tuple[list[dict], dict | None]:
    """Spring 책 응답(BookResponse.Page)과 같은 모양: 색·side 대문자, x·y 소수 1자리, owner 뺌"""
    blocks = [{"paragraphs": t.paragraphs, "x": round(t.x, 1), "y": round(t.y, 1), "color": t.color.upper()} for t in tbs]
    word = None if sw is None else {"text": sw.text, "color": sw.color, "pieces": [
        {"text": p.text, "x": round(p.x, 1), "y": round(p.y, 1), "side": p.side.upper()} for p in sw.pieces]}
    return blocks, word


def _old_paras(page: dict) -> Paras:
    return [b["paragraphs"] for b in page.get("textBlocks") or []]


def _cards(only: str | None) -> list[str]:
    names = sorted(p.parent.name for p in SAMPLES.glob("*/story.json"))
    if only:
        want = only.split(",")
        names = [n for n in names if n in want]
    return names


def _story(card: str) -> dict:
    return json.loads((SAMPLES / card / "story.json").read_text(encoding="utf-8"))


def _load_result() -> dict:
    return json.loads(RESULT.read_text(encoding="utf-8")) if RESULT.exists() else {"cards": {}}


def _save_result(res: dict) -> None:
    RESULT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def _mock() -> None:
    from firstory import llm, mock
    llm.set_structured_override(mock.fake_structured)   # FIRSTORY_MOCK은 스크립트에서 안 먹는다


def arrange(card: str, page: dict, image: bytes, costs: list) -> dict:
    """쪽 하나 자리 찾기(다시 그리지 않음). result.json의 쪽 항목"""
    blocks = rewrap(_old_paras(page))
    words = sound_words(page["text"])
    sfx = SfxAsk(word=words[0], text=page["text"], cast=[]) if words else None
    wanted: list = []
    tbs, sw = il._arrange(page["pageNo"], image, blocks, costs, lambda bl, where: wanted.append(where) or None, sfx)
    new = [t.paragraphs for t in tbs]
    if not same_text(_old_paras(page), new):
        raise RuntimeError(f"{card} {page['pageNo']}쪽: 배치 뒤 글이 달라짐")
    tb, word = to_front(tbs, sw)
    return {"textBlocks": tb, "soundWord": word, "needsRedraw": wanted[0] if wanted else None,
            "word": words[0] if words else None}


# ── place ──
def place(args) -> None:
    if args.mock:
        _mock()
    OUT.mkdir(parents=True, exist_ok=True)
    res = _load_result()
    todo = [(c, p) for c in _cards(args.cards) for p in _story(c)["pages"]]
    if args.limit:
        todo = todo[:args.limit]
    tin = tout = 0
    for i, (card, page) in enumerate(todo):
        costs: list = []
        t0 = time.time()
        img = SAMPLES / card / page["image"]
        entry = arrange(card, page, img.read_bytes(), costs)
        entry.update(image=str(img), redrawn=False)
        res["cards"].setdefault(card, {"pages": {}})["pages"][str(page["pageNo"])] = entry
        tin += sum(c.input_tokens for c in costs)
        tout += sum(c.output_tokens for c in costs)
        print(f"{i + 1}/{len(todo)} {card} {page['pageNo']}쪽 {time.time() - t0:.1f}초"
              f"{' 자리없음' if entry['needsRedraw'] else ''}{' 의성어빠짐' if entry['word'] and not entry['soundWord'] else ''}", flush=True)
        _save_result(res)   # 중간에 멈춰도 여기까지는 남는다
    res.setdefault("tokens", {"in": 0, "out": 0})
    res["tokens"]["in"] += tin
    res["tokens"]["out"] += tout
    _save_result(res)
    preview(res)
    print(OUT / "index.html", f"tokens in={tin} out={tout}")


# ── 미리보기 ──
def _blocks_html(blocks: list[dict]) -> str:
    out = []
    for b in blocks:
        paras = "".join(f'<p>{"<br>".join(_bold(l) for l in para)}</p>' for para in b["paragraphs"])
        out.append(f'<div class="tb {b["color"].lower()}" style="left:{b["x"]}%;top:{b["y"]}%">{paras}</div>')
    return "".join(out)


def _bold(line: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(line))


def _word_html(w: dict | None) -> str:
    if not w:
        return ""
    return "".join(f'<span class="sw" style="left:{p["x"]}%;top:{p["y"]}%;color:{w["color"]}">{html.escape(p["text"])}</span>'
                   for p in w["pieces"])


def preview(res: dict) -> None:
    (OUT / "img").mkdir(parents=True, exist_ok=True)
    shutil.copy(FONT_PATH, OUT / "font.woff2")
    rows, n, no_room, has_w, miss_w, redrawn = [], 0, 0, 0, 0, 0
    for card in sorted(res["cards"]):
        story = _story(card)
        old_pages = {p["pageNo"]: p for p in story["pages"]}
        rows.append(f'<h2>{html.escape(story["title"])} <small>{card} · {html.escape(story["cardTitle"])}</small></h2>')
        for no, e in sorted(res["cards"][card]["pages"].items(), key=lambda kv: int(kv[0])):
            n += 1
            old = old_pages[int(no)]
            src = SAMPLES / card / old["image"]
            old_name = f"img/{card}-{src.name}"
            shutil.copy(src, OUT / old_name)
            new_name = f"img/{card}-redraw-{int(no):02d}.webp" if e.get("redrawn") else old_name
            flags = []
            if e["needsRedraw"]:
                no_room += 1
                flags.append(f'<span class="flag warn">{"다시 그려도 " if e.get("redrawn") else ""}자리 없음 → 가장 조용한 곳</span>')
            if e.get("redrawn"):
                redrawn += 1
                flags.append('<span class="flag new">다시 그림</span>')
            if e["word"]:
                if e["soundWord"]:
                    has_w += 1
                    flags.append('<span class="flag ok">의성어 있음</span>')
                else:
                    miss_w += 1
                    flags.append('<span class="flag warn">의성어 빠짐</span>')
            key = f"{card}:{no}"
            rows.append(f"""
<section><div class="meta"><label><input type="checkbox" value="{key}"> <b>{int(no)}쪽</b> 다시 그리기</label> {' '.join(flags)}</div>
<div class="pair">
  <figure><div class="pg"><img src="{old_name}">{_blocks_html(old.get('textBlocks') or [])}</div><figcaption>지금 (11/6 배치, 글자 2.35%로 보면 잘림)</figcaption></figure>
  <figure><div class="pg"><img src="{new_name}">{_blocks_html(e['textBlocks'])}{_word_html(e['soundWord'])}</div><figcaption>새 배치{' + 의성어' if e['soundWord'] else ''}</figcaption></figure>
</div></section>""")
    tok = res.get("tokens", {"in": 0, "out": 0})
    head = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>샘플 동화 새 배치</title>
<style>
@font-face{{font-family:K;src:url(font.woff2)}}
body{{font-family:-apple-system,sans-serif;margin:16px;background:#f6f5f2;color:#222}}
h2{{margin:36px 0 10px}} h2 small{{font-weight:400;color:#777;font-size:14px}}
section{{margin:0 0 24px}} .meta{{font-size:14px;margin:4px 0 8px}}
.flag{{display:inline-block;font-size:12px;padding:1px 7px;border-radius:9px;margin-left:4px}}
.flag.warn{{background:#ffe1d6;color:#a3360c}} .flag.ok{{background:#dff3e2;color:#1d6b2c}} .flag.new{{background:#dfe9ff;color:#1d3f8f}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} figure{{margin:0}} figcaption{{font-size:12px;color:#666;margin-top:4px}}
@media (max-width:700px){{.pair{{grid-template-columns:1fr}}}}
.pg{{position:relative;container-type:inline-size;aspect-ratio:{W}/{H};overflow:hidden}} .pg img{{width:100%;height:100%;object-fit:cover;display:block}}
.tb{{position:absolute;font-family:K;font-size:{FONT_RATIO * 100:g}cqw;line-height:1.55;white-space:nowrap}} .tb p{{margin:0 0 .93em}}
.tb.dark{{color:#4a4a4a}} .tb.light{{color:#fff}}
.sw{{position:absolute;transform:translate(-50%,-50%);font-family:K;font-weight:700;font-size:{PIECE_RATIO * 100:g}cqw;white-space:nowrap}}
#pick{{position:sticky;top:0;background:#fff;border:1px solid #ddd;border-radius:8px;padding:10px;z-index:2}}
#pick textarea{{width:100%;box-sizing:border-box;font-family:monospace}}
</style>
<h1>샘플 동화 새 배치 미리보기</h1>
<p>{n}쪽 · 자리 없음 {no_room} · 다시 그림 {redrawn} · 의성어 있음 {has_w} / 빠짐 {miss_w} · 토큰 입력 {tok['in']} / 출력 {tok['out']}</p>
<p>왼쪽은 11/6 배치를 지금 글자 크기로 그린 것, 오른쪽은 새 배치예요. 다시 그릴 쪽에 체크하면 아래 칸에 목록이 생겨요.</p>
<div id="pick">다시 그릴 쪽 (<span id="cnt">0</span>쪽, 약 <span id="won">0</span>원): <textarea id="sel" rows="2" readonly></textarea></div>
<script>
document.addEventListener('change', () => {{
  const v = [...document.querySelectorAll('input[type=checkbox]:checked')].map(x => x.value);
  document.getElementById('sel').value = v.join(',');
  document.getElementById('cnt').textContent = v.length;
  document.getElementById('won').textContent = v.length * 40;
}});
</script>"""
    (OUT / "index.html").write_text(head + "".join(rows), encoding="utf-8")


# ── redraw / revert ──
def redraw_prompt(sizes: list[tuple[float, float]], where: list[str]) -> str:
    """첨부한 쪽 그림을 같은 장면·인물·화풍으로, 글 들어갈 빈 곳만 남겨 다시 그리는 지시 (원래 그림 지시·시트가 없다)"""
    return ("Redraw the attached picture-book page. Keep the same scene, the same characters (same species, colors, markings, "
            "proportions, outfits and facial expressions), the same objects, the same time of day and light, and the same art style. "
            "Keep the composition as close to the original as possible; only move things as much as needed to open up the space below. "
            "Full-bleed illustration, no text, no speech bubbles, no borders.\n" + il.layout_prompt(sizes, where))


def _keys(spec: str) -> list[tuple[str, str]]:
    out = []
    for k in spec.split(","):
        card, no = k.strip().split(":")
        out.append((card, str(int(no))))
    return out


def _blank() -> bytes:
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (W, H), "white").save(buf, "WEBP")
    return buf.getvalue()


def redraw(args) -> None:
    from PIL import Image
    import io
    if args.mock:
        _mock()
        il.set_image_override(lambda prompt, refs: _blank())
    res = _load_result()
    res.setdefault("tokens", {"in": 0, "out": 0})
    for card, no in _keys(args.pages):
        entry = res["cards"][card]["pages"][no]
        page = next(p for p in _story(card)["pages"] if str(p["pageNo"]) == no)
        blocks = rewrap(_old_paras(page))
        where = entry.get("before", entry)["needsRedraw"] or ["left top", "right top"][:len(blocks)]
        src = SAMPLES / card / page["image"]
        t0 = time.time()
        try:
            img, tin, tout = il._edit(redraw_prompt([layout.block_size(b) for b in blocks], where), [(src.name, src.read_bytes())])
        except Exception as e:  # noqa: BLE001 — 한 장 실패가 나머지를 막지 않는다
            print(f"{card} {no}쪽 다시 그리기 실패: {type(e).__name__}", flush=True)
            continue
        size = Image.open(io.BytesIO(img)).size
        if size != (W, H):
            print(f"{card} {no}쪽: 그림 크기 {size} ≠ {(W, H)} → 옛 그림 그대로", flush=True)
            continue
        name = OUT / "img" / f"{card}-redraw-{int(no):02d}.webp"
        name.parent.mkdir(parents=True, exist_ok=True)
        Image.open(io.BytesIO(img)).save(name, "WEBP", quality=90)
        costs: list = []
        new = arrange(card, page, name.read_bytes(), costs)
        new.update(image=str(src), redrawn=True, redrawImage=str(name), before=entry.get("before", entry))
        res["cards"][card]["pages"][no] = new
        res["tokens"]["in"] += sum(c.input_tokens for c in costs)
        res["tokens"]["out"] += sum(c.output_tokens for c in costs)
        res.setdefault("imageTokens", {"in": 0, "out": 0, "images": 0})
        res["imageTokens"]["in"] += tin
        res["imageTokens"]["out"] += tout
        res["imageTokens"]["images"] += 1
        _save_result(res)
        print(f"{card} {no}쪽 다시 그림 {time.time() - t0:.1f}초{' (그래도 자리 없음)' if new['needsRedraw'] else ''}", flush=True)
    preview(res)
    print(OUT / "index.html", res.get("imageTokens"))


def revert(args) -> None:
    res = _load_result()
    for card, no in _keys(args.pages):
        entry = res["cards"][card]["pages"][no]
        if entry.get("before"):
            res["cards"][card]["pages"][no] = entry["before"]
    _save_result(res)
    preview(res)


# ── export ──
KEEP_PAGE = ("pageNo", "text", "image", "textPosition")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def export_story(old: dict, pages: dict) -> dict:
    """옛 story.json에 쪽마다 textBlocks·soundWord만 바꿔 넣는다 (나머지 칸·순서 그대로)"""
    new = json.loads(json.dumps(old))
    for pg in new["pages"]:
        e = pages[str(pg["pageNo"])]
        pg["textBlocks"] = e["textBlocks"]
        pg["soundWord"] = e["soundWord"]
    return new


def check_story(old: dict, new: dict) -> list[str]:
    """문제 목록 (비면 통과). 쪽 글은 메시지에 넣지 않는다"""
    bad = [f"{k} 바뀜" for k in set(old) | set(new) if k != "pages" and old.get(k) != new.get(k)]
    if len(old["pages"]) != len(new["pages"]):
        return bad + ["쪽 수 바뀜"]
    for o, n in zip(old["pages"], new["pages"]):
        at = f"{o['pageNo']}쪽"
        bad += [f"{at} {k} 바뀜" for k in KEEP_PAGE if o.get(k) != n.get(k)]
        tbs = n.get("textBlocks") or []
        if not 1 <= len(tbs) <= 3:
            bad.append(f"{at} textBlocks 개수 {len(tbs)}")
        for b in tbs:
            if not (0 <= b["x"] <= 100 and 0 <= b["y"] <= 100) or b["color"] not in ("DARK", "LIGHT"):
                bad.append(f"{at} textBlocks 자리·색")
        if tbs and not same_text(_old_paras(o), [b["paragraphs"] for b in tbs]):
            bad.append(f"{at} textBlocks 글이 원래와 다름")
        sw = n.get("soundWord")
        if sw is None:
            continue
        words = sound_words(n["text"])
        pieces = sw.get("pieces") or []
        if not words or sw.get("text") != words[0]:
            bad.append(f"{at} soundWord 말이 본문 별표 말과 다름")
        if not HEX.match(str(sw.get("color"))):
            bad.append(f"{at} soundWord 색")
        if not 1 <= len(pieces) <= 2:
            bad.append(f"{at} soundWord 조각 수 {len(pieces)}")
        for p in pieces:
            if not p.get("text") or not (0 <= p["x"] <= 100 and 0 <= p["y"] <= 100) or p.get("side") not in ("LEFT", "RIGHT", "CENTER"):
                bad.append(f"{at} soundWord 조각")
        if "".join(p.get("text", "") for p in pieces) != re.sub(r"\s", "", str(sw.get("text"))):
            bad.append(f"{at} soundWord 조각을 이으면 말과 다름")
    return bad


BACKUP = FIRSTORY / "샘플동화-1106"
ZIP = FIRSTORY / "샘플동화_1117.zip"


def export(args) -> None:
    import zipfile
    res = _load_result()
    cards = _cards(None)
    out, bad = {}, []
    for card in cards:
        old = _story(card)
        got = res["cards"].get(card, {}).get("pages", {})
        missing = [p["pageNo"] for p in old["pages"] if str(p["pageNo"]) not in got]
        if missing:
            bad.append(f"{card}: 배치 안 한 쪽 {missing}")
            continue
        out[card] = export_story(old, got)
        bad += [f"{card} {m}" for m in check_story(old, out[card])]
    if bad:
        print("내보내기 멈춤 — 아무것도 쓰지 않음:\n  " + "\n  ".join(bad))
        sys.exit(1)
    if not BACKUP.exists():
        shutil.copytree(SAMPLES, BACKUP)
        print("원본 보관:", BACKUP)
    for card in cards:
        (SAMPLES / card / "story.json").write_text(json.dumps(out[card], ensure_ascii=False, indent=2), encoding="utf-8")
        for no, e in res["cards"][card]["pages"].items():
            if e.get("redrawn"):
                page = next(p for p in out[card]["pages"] if str(p["pageNo"]) == no)
                shutil.copy(e["redrawImage"], SAMPLES / card / page["image"])
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:   # 카드 폴더만 (화면 기록·.DS_Store 빼고)
        for card in cards:
            for f in sorted((SAMPLES / card).iterdir()):
                if f.suffix in (".json", ".webp"):
                    z.write(f, f"샘플동화/{card}/{f.name}")
    print("내보냄:", SAMPLES, ZIP, f"{ZIP.stat().st_size / 1e6:.1f}MB")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("place")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--cards")
    r = sub.add_parser("redraw")
    r.add_argument("--pages", required=True)
    r.add_argument("--mock", action="store_true")
    v = sub.add_parser("revert")
    v.add_argument("--pages", required=True)
    sub.add_parser("export")
    args = ap.parse_args()
    {"place": place, "redraw": redraw, "revert": revert, "export": export}[args.cmd](args)


if __name__ == "__main__":
    main()
