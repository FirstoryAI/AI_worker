"""render: 단계별 JSON + book.html (아이와 읽는 화면 + 부모용 가이드 패널)

book.html은 프론트 읽기 화면(Frontend_MainPage `StoryFlipPage`·`StoryTextBlocks`·`SoundWord`)과
동화 상세(`StoryDetailPage` 줄거리)를 따라 그린다 (#122). 그림 칸 폭 기준(cqw) 글자 크기·자리가 프론트와 같다.
- 글 덩어리(text_blocks): 왼쪽 위 모서리를 x·y%에, 2.35cqw, dark/light 색
- 의성어(sound_word.pieces): 조각 가운데를 x·y%에, 2.5cqw, 서버 색, side에 따라 기울기. 본문의 **말**은 별표만 지움
- 덩어리가 없는 쪽은 옛 글 상자(text_position 위/아래)
글꼴은 프론트와 같은 파일을 출력 폴더 `_fonts/`에 두면 쓴다 (없으면 기본 글꼴). 예:
  git -C ../Frontend_MainPage show origin/main:src/assets/fonts/MemomentKkukkukk.woff2 > out/_fonts/MemomentKkukkukk.woff2
저장된 실행 다시 그리기 (OpenAI 호출 없음): uv run python -m firstory.nodes.render out/<실행 폴더>
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from .. import storage
from ..config import config
from ..schemas import Illustrations, ReadingGuide, StoryText
from ..state import PipelineState

_e = html.escape
_SFX = re.compile(r"\*\*(.+?)\*\*")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ROTATE = {"left": -10, "right": 10, "center": 0}
_FONTS = [("Memoment Kkukkukk", "MemomentKkukkukk.woff2", 400), ("Hippie", "Hippie-KS.woff2", 400),
          ("Pretendard", "Pretendard-Regular.woff2", 400), ("Pretendard", "Pretendard-SemiBold.woff2", 600)]


def _text(t: str) -> str:
    """프론트 StoryText처럼 본문의 **의성어** 표시는 별표만 지운다 (말은 그림 위에 크게 띄운다). 나머지는 escape."""
    return _e(_SFX.sub(r"\1", t))


def _dump(prefix: str, state: PipelineState):
    def j(name, obj):
        if obj is None:
            return
        data = obj.model_dump() if hasattr(obj, "model_dump") else obj
        storage.write_text(storage.join(prefix, name), json.dumps(data, ensure_ascii=False, indent=2, default=str))

    j("00-context.json", state.get("context"))
    j("01-interview.json", {"turns": [t.model_dump() for t in state.get("interview_turns", [])],
                            "done_by": state.get("interview_done_by"), "summary": state.get("interview_summary"),
                            "parent_summary": state.get("interview_parent_summary")})
    j("02-design.json", state.get("story_design"))
    j("02-strategy.json", state.get("strategy"))
    j("03-draft.json", state.get("story_draft"))
    j("03-story.json", state.get("story"))
    j("04-guide.json", state.get("guide"))
    j("05-illustrations.json", state.get("illustrations"))
    j("06-narration.json", state.get("narration"))
    j("99-cost.json", [c.model_dump() for c in state.get("cost", [])])


def _aspect() -> str:
    w, _, h = config.image_size.partition("x")
    return f"{w} / {h}" if w.isdigit() and h.isdigit() else "16 / 9"


def _blocks(blocks) -> str:
    """StoryTextBlocks: 덩어리 > 문단 > 줄. 줄마다 한 줄로 (서버가 나눈 그대로)"""
    out = []
    for b in blocks:
        paras = "".join(
            '<p class="para">' + "".join(f'<span class="line">{_text(line)}</span>' for line in para) + "</p>"
            for para in b.paragraphs)
        out.append(f'<div class="block" data-color="{_e(b.color)}" style="left:{b.x}%;top:{b.y}%">{paras}</div>')
    return f'<div class="blocks">{"".join(out)}</div>'


def _sound(sw) -> str:
    """SoundWord: 조각 가운데를 x·y%에. 색이 #RRGGBB가 아니거나 자리가 그림 밖이면 그 조각은 안 띄운다 (프론트와 같음)"""
    if not sw or not sw.pieces or not _HEX.match(sw.color or ""):
        return ""
    return "".join(
        f'<span class="sound" style="left:{p.x}%;top:{p.y}%;color:{sw.color};--rotate:{_ROTATE.get(p.side, 0)}deg">{_e(p.text)}</span>'
        for p in sw.pieces if p.text and 0 <= p.x <= 100 and 0 <= p.y <= 100)


def _copy(p) -> str:
    """덩어리가 없는 쪽(옛 결과·그림 실패): 그림이 비워 둔 위/아래에 글 상자 하나"""
    lines = "".join(f"<p>{_text(line)}</p>" for line in p.text.split("\n") if line.strip())
    return f'<div class="copy" data-position="{_e(p.text_position)}">{lines}</div>'


def build_html(state: PipelineState) -> str:
    story, guide, ill = state["story"], state.get("guide"), state.get("illustrations")
    here = storage.local_path(state["output_prefix"])

    def src(key: Optional[str]) -> Optional[str]:  # 그림만 다시 그린 실행은 안 바뀐 쪽이 이전 실행 폴더에 있다
        return os.path.relpath(storage.local_path(key), here) if key else None

    pages = {p.order: p for p in (ill.pages if ill else [])}
    img = {o: src(p.path) for o, p in pages.items() if p.status == "completed" and p.path}
    cover = front = back = sheet = None
    if ill:
        cover, sheet = src(ill.cover), src(ill.character_sheet_path)
        front, back = src(ill.front_cover), src(ill.back_cover)   # 앞표지 = 정사각형 표지, 뒤표지도 정사각형 (#125). 옛 동화는 가로
    synopsis = guide.synopsis if guide else ""
    prompts_after = {}
    for q in (guide.prompts if guide else []):
        prompts_after.setdefault(q.after_page, []).append(q)
    n = len(story.pages)

    # 동화 한 눈에 보기 (StoryDetailPage): 정사각형 표지 + 제목 + 줄거리 (가운데 맞춤, 6줄까지)
    art = cover or sheet
    slides = [f"""
    <section class="slide detail" data-label="한 눈에 보기">
      <div class="detail-cover">{f'<img src="{_e(art)}" alt="">' if art else '<div class="ph"></div>'}</div>
      <div class="detail-info">
        <h1>{_e(story.title)}</h1>
        {f'<p class="synopsis">{_e(synopsis)}</p>' if synopsis else '<p class="synopsis empty">줄거리 없음</p>'}
        <p class="meta">줄거리 {len(synopsis)}자 · 상세 화면처럼 6줄까지 보여요</p>
      </div>
    </section>"""]
    if front:
        slides.append(f"""
    <section class="slide" data-label="앞표지"><div class="scene book-cover"><img src="{_e(front)}" alt=""></div></section>""")
    for p in story.pages:
        pi = pages.get(p.order)
        has_img = p.order in img
        body = _blocks(pi.text_blocks) if pi and pi.text_blocks else _copy(p)
        sw = _sound(pi.sound_word) if pi and has_img else ""
        slides.append(f"""
    <section class="slide" data-label="{p.order} / {n}쪽">
      <div class="scene">
        {f'<img src="{_e(img[p.order])}" alt="">' if has_img else f'<div class="ph"><span>{_e(p.image_prompt)}</span></div>'}
        {sw}{body}
      </div>
    </section>""")
        for q in prompts_after.get(p.order, []):
            slides.append(f"""
    <section class="slide question" data-label="{p.order}쪽 뒤 질문">
      <div class="bubble"><small>{_e(q.purpose)}</small><p>{_e(q.text)}</p></div>
      <p class="skip">{_e(q.parent_hint or '아이가 말하기 싫어하면 그냥 넘어가도 괜찮아요')}</p>
    </section>""")
    if back:
        slides.append(f"""
    <section class="slide" data-label="뒤표지"><div class="scene book-cover"><img src="{_e(back)}" alt=""></div></section>""")

    panel = ""
    if guide:
        design = state.get("story_design")
        mirrored = getattr(design, "mirrored_situation", None) or (design.get("mirrored_situation") if isinstance(design, dict) else None)
        starters = "".join(
            f'<div class="starter"><div class="when">p.{q.after_page} 뒤 · {_e(q.purpose)}</div><div class="say">“{_e(q.text)}”</div>'
            f'<div class="quiet">{_e(q.parent_hint or "")}</div></div>' for q in guide.prompts)
        sounds = "".join(
            f'<li>{o}쪽 <b style="color:{_e(pi.sound_word.color)}">{_e(pi.sound_word.text)}</b> · 조각 {len(pi.sound_word.pieces)}</li>'
            for o, pi in sorted(pages.items()) if pi.sound_word)
        starred = [p.order for p in story.pages if _SFX.search(p.text)]
        panel = f"""
  <aside id="library">
    <h2>부모용 · 읽기 전에</h2>
    <div class="card"><h3>{_e(story.title)}</h3><p>{_e(guide.before_reading.intent)}</p></div>
    <h4>함께 읽을 때</h4><ul>{''.join(f'<li>{_e(t)}</li>' for t in guide.before_reading.tips)}</ul>
    <h4>이야기 속 질문</h4>{starters}
    <h4>다 읽은 뒤</h4><p class="say">“{_e(guide.after_reading.bridge_question)}”</p>
    {f'<p class="quiet">{_e(guide.after_reading.if_undecided)}</p>' if guide.after_reading.if_undecided else ''}
    <h4>그림 위 의성어·의태어</h4>
    {f'<ul>{sounds}</ul>' if sounds else '<p class="quiet">띄운 말 없음</p>'}
    <p class="quiet">본문 별표 말 있는 쪽: {', '.join(map(str, starred)) or '없음'}</p>
    <details><summary>생성 근거</summary>
      <p><b>인터뷰 정리</b> {_e(state.get('interview_summary') or '')}</p>
      {f"<p><b>간접화</b> {_e(mirrored)}</p>" if mirrored else ''}
    </details>
  </aside>"""

    fonts_dir = os.path.relpath(config.output_root / "_fonts", here)
    faces = "".join(
        f"@font-face{{font-family:'{name}';src:url('{fonts_dir}/{file}') format('woff2');font-weight:{w};font-display:swap}}"
        for name, file, w in _FONTS)

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(story.title)} — FIRSTORY</title>
<style>
{faces}
:root{{--font-title:'Memoment Kkukkukk','Pretendard',-apple-system,"Apple SD Gothic Neo",sans-serif;--font-sound:'Hippie','Memoment Kkukkukk','Pretendard',sans-serif;
--font-body:'Pretendard',-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;--wall:#2b1e17;--paper:#fffcef;--ink:#3a2f2a;--accent:#faa07c;--soft:#f3e7d8;--dim:#8a7d75}}
*{{box-sizing:border-box}}body{{margin:0;font-family:var(--font-body);background:var(--wall);color:var(--ink);display:grid;grid-template-columns:1fr 360px;min-height:100vh}}
@media(max-width:900px){{body{{grid-template-columns:1fr}}#library{{display:none}}}}
#book{{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:48px 24px 24px;cursor:pointer;user-select:none}}
.slide{{display:none;width:min(1100px,100%)}}.slide.active{{display:block}}
#label{{color:#e9dccb;font-size:14px;min-height:20px}}
.tools{{position:absolute;top:14px;right:24px;color:#e9dccb;font-size:13px;cursor:default}}
/* 그림 칸 (StoryFlipPage .flipSceneImage): 가로 기준 cqw */
.scene{{position:relative;width:100%;aspect-ratio:{_aspect()};container-type:inline-size;overflow:hidden;border-radius:6px;background:var(--paper);box-shadow:0 12px 40px rgb(0 0 0 / 35%)}}
.scene>img{{display:block;width:100%;height:100%;object-fit:cover}}
/* 앞·뒤표지 (StoryReader .coverBook): 정사각형, 가로 그림(옛 동화)은 가운데를 잘라 보여 줌 */
.scene.book-cover{{width:min(620px,100%);margin:0 auto;aspect-ratio:1}}
.ph{{display:flex;width:100%;height:100%;align-items:center;justify-content:center;padding:32px;color:var(--dim);font-size:14px;line-height:1.6;background:var(--soft)}}
/* StoryTextBlocks */
.blocks{{position:absolute;inset:0;pointer-events:none}}
.block{{position:absolute;color:#4a4a4a;font-family:var(--font-title);font-size:2.35cqw;line-height:1.55;text-align:left;white-space:nowrap}}
.block[data-color=light]{{color:#fff;text-shadow:0 1px 3px rgb(0 0 0 / 30%)}}
.para{{margin:0 0 .6em}}.para:last-child{{margin-bottom:0}}.line{{display:block}}
/* SoundWord */
.sound{{position:absolute;z-index:1;font-family:var(--font-sound);font-size:2.5cqw;line-height:1;white-space:nowrap;transform:translate(-50%,-50%) rotate(var(--rotate,0deg));text-shadow:0 .05em .1em rgb(40 25 10 / 22%);pointer-events:none}}
/* 옛 글 상자 (.readerCopy) */
.copy{{position:absolute;left:6%;right:6%;padding:.8cqw 1.6cqw;color:#4a4a4a;font-family:var(--font-title);font-size:clamp(19px,2cqw,28px);line-height:1.34;text-align:center;background:rgb(255 255 255 / 72%);border-radius:1.2cqw}}
.copy[data-position=top]{{top:3.28%}}.copy[data-position=bottom]{{bottom:3.28%}}.copy p{{margin:0 0 .21cqw}}
/* 자리 보기: 덩어리·조각 테두리 */
body.outline .block{{outline:1.5px dashed rgb(0 120 255 / 80%)}}body.outline .sound{{outline:1.5px dashed rgb(255 0 120 / 80%)}}
/* 동화 한 눈에 보기 (StoryDetailPage) */
.detail.active{{display:flex;align-items:center;justify-content:center;gap:56px;min-height:60vh;color:#fff}}
.detail-cover{{width:min(360px,40%);aspect-ratio:1;transform:rotate(-4deg);box-shadow:0 18px 40px rgb(0 0 0 / 45%);border-radius:6px;overflow:hidden;flex:none}}
.detail-cover img{{display:block;width:100%;height:100%;object-fit:cover}}
.detail-info{{width:485px;max-width:52%}}.detail-info h1{{margin:0;font:400 50px/1.304 var(--font-title);letter-spacing:-1.5px;word-break:keep-all}}
.synopsis{{display:-webkit-box;width:404px;max-width:100%;margin:44px 0 0 14px;overflow:hidden;font:400 20px/1.55 var(--font-body);text-align:center;word-break:keep-all;-webkit-box-orient:vertical;-webkit-line-clamp:6}}
.synopsis.empty{{color:#bba}}.meta{{margin:28px 0 0 14px;color:#bba;font-size:13px}}
.question.active{{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh}}
.bubble{{background:#fff;border:3px solid var(--accent);border-radius:32px;padding:40px 48px;max-width:640px;text-align:center}}
.bubble small{{display:block;color:var(--accent);font-weight:700;letter-spacing:.08em;font-size:13px;margin-bottom:12px}}
.bubble p{{font:400 30px/1.5 var(--font-title);margin:0;word-break:keep-all}}.skip{{color:#e9dccb;font-size:14px;margin-top:24px}}
#library{{background:#fff;padding:28px 24px;overflow:auto;max-height:100vh;font-size:14px;line-height:1.6;position:sticky;top:0}}
#library h2{{font-size:13px;letter-spacing:.1em;color:var(--dim);margin:0 0 16px}}#library h3{{margin:0 0 10px;font-size:18px}}
#library h4{{margin:24px 0 8px;font-size:13px;color:var(--accent);letter-spacing:.06em}}.card{{background:var(--soft);border-radius:16px;padding:16px}}
ul{{padding-left:18px;margin:0}}.starter{{border-left:3px solid var(--soft);padding:4px 0 4px 12px;margin:0 0 14px}}
.when{{font-size:12px;color:var(--dim)}}.say{{font-size:15px;margin:4px 0;font-weight:600}}.quiet{{font-size:12px;color:var(--dim)}}
details{{margin-top:28px;font-size:12px;color:var(--dim)}}
.progress{{position:absolute;top:20px;left:24px;right:200px;height:3px;background:rgb(255 255 255 / 15%);border-radius:2px}}.progress i{{display:block;height:100%;background:var(--accent);border-radius:2px;transition:width .3s}}
</style></head><body>
<main id="book"><div class="progress"><i id="bar"></i></div>
<label class="tools" onclick="event.stopPropagation()"><input type="checkbox" id="outline"> 자리 테두리</label>
{''.join(slides)}<div id="label"></div><p id="hint" style="color:#bba;font-size:13px;margin:0">→ 방향키 또는 클릭 · ← 뒤로</p></main>{panel}
<script>
const s=[...document.querySelectorAll('.slide')];let i=0;
const show=n=>{{i=Math.max(0,Math.min(s.length-1,n));s.forEach((e,k)=>e.classList.toggle('active',k===i));bar.style.width=((i+1)/s.length*100)+'%';label.textContent=s[i].dataset.label||''}};
document.getElementById('book').addEventListener('click',()=>show(i+1));
document.getElementById('outline').addEventListener('change',e=>document.body.classList.toggle('outline',e.target.checked));
addEventListener('keydown',e=>{{if(e.key==='ArrowRight'||e.key===' ')show(i+1);if(e.key==='ArrowLeft')show(i-1)}});show(0);
</script></body></html>"""


def render(state: PipelineState) -> dict:
    prefix = state["output_prefix"]
    _dump(prefix, state)
    storage.write_text(storage.join(prefix, "book.html"), build_html(state))
    return {"status": "reviewing"}


def rerender(run_dir: str | Path) -> Path:
    """저장된 실행 폴더(03-story·04-guide·05-illustrations JSON)로 book.html만 다시 그린다. OpenAI 호출 없음."""
    run = Path(run_dir).resolve()
    def read(name: str):
        path = run / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    story, guide, ill = read("03-story.json"), read("04-guide.json"), read("05-illustrations.json")
    interview, design = read("01-interview.json") or {}, read("02-design.json")
    state = {
        "story": StoryText.model_validate(story),
        "guide": ReadingGuide.model_validate(guide) if guide else None,
        "illustrations": Illustrations.model_validate(ill) if ill else None,
        "interview_summary": interview.get("summary"),
        "story_design": SimpleNamespace(mirrored_situation=(design or {}).get("mirrored_situation")),
        "output_prefix": os.path.relpath(run, config.output_root.resolve()),
    }
    out = run / "book.html"
    out.write_text(build_html(state), encoding="utf-8")
    return out


if __name__ == "__main__":
    for d in sys.argv[1:]:
        print(rerender(d))
