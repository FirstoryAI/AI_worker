"""render: 단계별 JSON + book.html (아이와 읽는 화면 + 부모용 가이드 패널)"""
from __future__ import annotations

import html
import json
import os
import re

from .. import storage
from ..state import PipelineState

_e = html.escape
_SFX = re.compile(r"\*\*(.+?)\*\*")


def _text(t: str) -> str:
    """본문의 **의성어** 표시를 굵은 강조로. 나머지는 escape."""
    return _SFX.sub(r'<b class="sfx">\1</b>', _e(t))


def _dump(prefix: str, state: PipelineState):
    def j(name, obj):
        if obj is None:
            return
        data = obj.model_dump() if hasattr(obj, "model_dump") else obj
        storage.write_text(storage.join(prefix, name), json.dumps(data, ensure_ascii=False, indent=2, default=str))

    j("00-context.json", state.get("context"))
    j("01-interview.json", {"turns": [t.model_dump() for t in state.get("interview_turns", [])],
                            "done_by": state.get("interview_done_by"), "summary": state.get("interview_summary")})
    j("02-design.json", state.get("story_design"))
    j("02-strategy.json", state.get("strategy"))
    j("03-draft.json", state.get("story_draft"))
    j("03-story.json", state.get("story"))
    j("04-guide.json", state.get("guide"))
    j("05-illustrations.json", state.get("illustrations"))
    j("99-cost.json", [c.model_dump() for c in state.get("cost", [])])


def build_html(state: PipelineState) -> str:
    story, guide, ill = state["story"], state.get("guide"), state.get("illustrations")
    here = storage.local_path(state["output_prefix"])

    def src(key: str) -> str:  # 그림만 다시 그린 실행은 안 바뀐 쪽이 이전 실행 폴더에 있다
        return os.path.relpath(storage.local_path(key), here)

    img = {p.order: src(p.path) for p in (ill.pages if ill else []) if p.status == "completed" and p.path}
    sheet = src(ill.character_sheet_path) if ill and ill.character_sheet_path else None
    prompts_after = {}
    for q in (guide.prompts if guide else []):
        prompts_after.setdefault(q.after_page, []).append(q)

    slides = [f"""
    <section class="slide cover">
      {f'<img src="{_e(sheet)}" alt="">' if sheet else '<div class="ph"></div>'}
      <h1>{_e(story.title)}</h1><p class="hint">→ 방향키 또는 클릭</p>
    </section>"""]
    for p in story.pages:
        slides.append(f"""
    <section class="slide page">
      {f'<img src="{_e(img[p.order])}" alt="">' if p.order in img else f'<div class="ph"><span>{_e(p.image_prompt)}</span></div>'}
      <p class="text">{_text(p.text)}</p>
    </section>""")
        for q in prompts_after.get(p.order, []):
            slides.append(f"""
    <section class="slide question">
      <div class="bubble"><small>{_e(q.purpose)}</small><p>{_e(q.text)}</p></div>
      <p class="skip">{_e(q.parent_hint or '아이가 말하기 싫어하면 그냥 넘어가도 괜찮아요')}</p>
    </section>""")

    g = guide
    panel = ""
    if g:
        starters = "".join(
            f'<div class="starter"><div class="when">p.{q.after_page} 뒤 · {_e(q.purpose)}</div><div class="say">“{_e(q.text)}”</div>'
            f'<div class="quiet">{_e(q.parent_hint or "")}</div></div>' for q in g.prompts)
        panel = f"""
  <aside id="library">
    <h2>부모용 · 읽기 전에</h2>
    <div class="card"><h3>{_e(story.title)}</h3><p>{_e(g.before_reading.intent)}</p></div>
    <h4>함께 읽을 때</h4><ul>{''.join(f'<li>{_e(t)}</li>' for t in g.before_reading.tips)}</ul>
    <h4>이야기 속 질문</h4>{starters}
    <h4>다 읽은 뒤</h4><p class="say">“{_e(g.after_reading.bridge_question)}”</p>
    {f'<p class="quiet">{_e(g.after_reading.if_undecided)}</p>' if g.after_reading.if_undecided else ''}
    <details><summary>생성 근거</summary>
      <p><b>인터뷰 정리</b> {_e(state.get('interview_summary') or '')}</p>
      {f"<p><b>간접화</b> {_e(state['story_design'].mirrored_situation)}</p>" if state.get('story_design') else ''}
    </details>
  </aside>"""

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(story.title)} — FIRSTORY</title>
<style>
:root{{--bg:#fbf6ee;--ink:#3a2f2a;--accent:#e8a87c;--soft:#f3e7d8;--dim:#8a7d75}}
*{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;background:var(--bg);color:var(--ink);display:grid;grid-template-columns:1fr 360px;min-height:100vh}}
@media(max-width:900px){{body{{grid-template-columns:1fr}}#library{{display:none}}}}
#book{{position:relative;display:flex;align-items:center;justify-content:center;padding:24px;cursor:pointer;user-select:none}}
.slide{{display:none;width:min(720px,100%);text-align:center}}.slide.active{{display:block}}
.slide img,.ph{{width:100%;aspect-ratio:1;object-fit:cover;border-radius:24px;box-shadow:0 12px 40px rgba(60,40,20,.15);background:var(--soft)}}
.ph{{display:flex;align-items:center;justify-content:center;padding:32px;color:var(--dim);font-size:14px;line-height:1.6}}
.cover h1{{font-size:40px;margin:28px 0 8px}}.hint{{color:var(--dim);font-size:14px}}
.page .text{{font-size:26px;line-height:1.65;margin:28px 12px 0;word-break:keep-all}}.sfx{{font-weight:800;font-size:1.2em;color:var(--accent)}}
.question.active{{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh}}
.bubble{{background:#fff;border:3px solid var(--accent);border-radius:32px;padding:40px 48px;max-width:640px}}
.bubble small{{display:block;color:var(--accent);font-weight:700;letter-spacing:.08em;font-size:13px;margin-bottom:12px}}
.bubble p{{font-size:30px;line-height:1.5;margin:0;word-break:keep-all}}.skip{{color:var(--dim);font-size:14px;margin-top:24px}}
#library{{background:#fff;border-left:1px solid #eadfd2;padding:28px 24px;overflow:auto;max-height:100vh;font-size:14px;line-height:1.6}}
#library h2{{font-size:13px;letter-spacing:.1em;color:var(--dim);margin:0 0 16px}}#library h3{{margin:0 0 10px;font-size:18px}}
#library h4{{margin:24px 0 8px;font-size:13px;color:var(--accent);letter-spacing:.06em}}.card{{background:var(--soft);border-radius:16px;padding:16px}}
ul{{padding-left:18px;margin:0}}.starter{{border-left:3px solid var(--soft);padding:4px 0 4px 12px;margin:0 0 14px}}
.when{{font-size:12px;color:var(--dim)}}.say{{font-size:15px;margin:4px 0;font-weight:600}}.quiet{{font-size:12px;color:var(--dim)}}
details{{margin-top:28px;font-size:12px;color:var(--dim)}}
.progress{{position:absolute;top:16px;left:24px;right:24px;height:3px;background:var(--soft);border-radius:2px}}.progress i{{display:block;height:100%;background:var(--accent);border-radius:2px;transition:width .3s}}
</style></head><body>
<main id="book"><div class="progress"><i id="bar"></i></div>{''.join(slides)}</main>{panel}
<script>
const s=[...document.querySelectorAll('.slide')];let i=0;
const show=n=>{{i=Math.max(0,Math.min(s.length-1,n));s.forEach((e,k)=>e.classList.toggle('active',k===i));bar.style.width=((i+1)/s.length*100)+'%'}};
document.getElementById('book').addEventListener('click',()=>show(i+1));
addEventListener('keydown',e=>{{if(e.key==='ArrowRight'||e.key===' ')show(i+1);if(e.key==='ArrowLeft')show(i-1)}});show(0);
</script></body></html>"""


def render(state: PipelineState) -> dict:
    prefix = state["output_prefix"]
    _dump(prefix, state)
    storage.write_text(storage.join(prefix, "book.html"), build_html(state))
    return {"status": "reviewing"}
