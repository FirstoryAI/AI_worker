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
            if e["needsRedraw"] and not e.get("redrawn"):
                no_room += 1
                flags.append('<span class="flag warn">자리 없음 → 가장 조용한 곳</span>')
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


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("place")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--cards")
    args = ap.parse_args()
    {"place": place}[args.cmd](args)


if __name__ == "__main__":
    main()
