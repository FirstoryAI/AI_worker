"""
뷰어 '프롬프트 실험' 화면 — 같은 입력·같은 인터뷰로 프롬프트 전략만 바꿔 뽑은 동화를 나란히 읽고 점수를 본다.
실행·저장은 firstory/lab.py. 결과는 out/lab/ 에 남아서 '지난 실험'으로 다시 열 수 있다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from firstory import lab

_SENT = re.compile(r"(?<=[.!?”\"])\s+")
_EXTRA = [("want", "원하는 것"), ("ever_since", "그 뒤로"), ("comfort_object", "위로 물건")]


def _name(k: str) -> str:
    return lab.PRESETS[k][0]


def _lines(text: str) -> str:
    """한 문장씩 줄바꿈. **의성어** 표시는 markdown 굵게로 그대로 보인다."""
    return "  \n".join(s.strip() for s in _SENT.split(text.replace("\n", " ")) if s.strip())


def _form(d: Path) -> dict:
    """evals/story_form_check 의 형식 수치. 없으면 빈 칸."""
    try:
        import story_form_check
        r = story_form_check.check(d)
        return {"문장/쪽": r["문장/쪽"], "어절/문장": r["어절/문장"], "의성어 쪽 %": r["의성어 쪽 %"]}
    except Exception:
        return {}


def _base_label(p: Path) -> str:
    story = lab._j(p / "03-story.json")
    return f"{p.name} · {story['title']}" if story else p.name


def _explain():
    st.subheader("전략")
    st.dataframe(pd.DataFrame([{"키": k, "전략": n, "무엇을 바꾸나": d} for k, (n, d, _) in lab.PRESETS.items()]),
                 hide_index=True, width="stretch")
    st.caption("전략 프롬프트: src/firstory/prompts/strategies/ · 상황별 흐름: prompts/arcs/ · 채점: prompts/story_judge.md")


def _sidebar(root: Path):
    inputs = sorted((root / "datasets" / "inputs").glob("*.json"))
    with st.sidebar:
        st.title("프롬프트 실험")
        st.caption("같은 입력·같은 인터뷰로 전략만 바꿔 뽑는다 (텍스트만)")
        sample = st.selectbox("샘플", inputs, format_func=lambda p: p.stem, key="lab_sample")
        bases = lab.base_runs(sample.stem)
        if bases:
            base = st.selectbox("기준 실행 (이 인터뷰를 그대로 씀)", bases, format_func=_base_label, key="lab_base")
        else:
            base = None
            st.info("이 샘플로 돌린 실행이 없어요. 아래 버튼으로 먼저 만들어요.")
        if st.button("이 샘플로 기준 새로 만들기 (텍스트만 · 2~3분)", width="stretch"):
            with st.spinner("스크립트 답변으로 인터뷰부터 동화까지 한 번 돌리는 중…"):
                lab.make_base(sample)
            st.rerun()
        keys = st.multiselect("전략", list(lab.PRESETS), default=list(lab.PRESETS), format_func=_name, key="lab_keys")
        judge_on = st.checkbox("채점하기 (전략마다 LLM 1회 추가)", value=True)
        workers = st.slider("동시에 돌릴 개수", 1, len(lab.PRESETS), 3)
        run = st.button("실험 시작", type="primary", width="stretch", disabled=not (base and keys))

        st.divider()
        past = lab.experiments()
        pick = st.selectbox("지난 실험", [None] + past, format_func=lambda p: "(선택)" if p is None else p.name, key="lab_pick")
        if pick is not None and st.button("불러오기", key="lab_load"):
            st.session_state["lab_exp"] = str(pick)
    return base, keys, judge_on, workers, run


def _scores(e: dict, ok: list[str]):
    variants = e["variants"]
    rows = [{"전략": _name(k), "제목": variants[k]["story"]["title"], **lab.score_row(variants[k]), **_form(variants[k]["dir"])}
            for k in ok]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("점수는 LLM이 매긴 1~5점이라 방향 참고용이에요. 고를 때는 아래 본문을 직접 읽어 주세요. "
               "설계 반영 = 설계의 쪽별 사건이 본문에 실제로 나온 수.")


def _side_by_side(e: dict, ok: list[str]):
    st.subheader("나란히 읽기")
    sel = st.multiselect("볼 전략", ok, default=ok[:3], format_func=_name, key="lab_sel")
    if not sel:
        return
    pages = {k: {p["order"]: p["text"] for p in e["variants"][k]["story"]["pages"]} for k in sel}
    for c, k in zip(st.columns(len(sel)), sel):
        c.markdown(f"##### {_name(k)}\n**{e['variants'][k]['story']['title']}**")
    for o in sorted(set().union(*pages.values())):
        with st.container(border=True):
            for c, k in zip(st.columns(len(sel)), sel):
                c.markdown(f"**{o}**  \n{_lines(pages[k].get(o, ''))}")


def _detail(e: dict, ok: list[str]):
    st.subheader("전략별 자세히")
    for t, k in zip(st.tabs([_name(k) for k in ok]), ok):
        v = e["variants"][k]
        d = v["design"]
        with t:
            st.caption(lab.PRESETS[k][1])
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**설계**")
                p = d["protagonist"]
                who = f"{p['name']} ({p['species']})"
                if d.get("supporting"):
                    who += f" · {d['supporting']['name']} ({d['supporting']['species']})"
                st.markdown(f"- 인물: {who}\n- 원인: {d.get('problem_cause', '')}")
                for f, label in _EXTRA:
                    if d.get(f):
                        st.markdown(f"- {label}: {d[f]}")
                if d.get("attempts"):
                    st.markdown("- 시도: " + " / ".join(f"{i}) {a['action']} → {a['result']}" for i, a in enumerate(d["attempts"], 1)))
                if d.get("refrain"):
                    st.markdown(f"- 반복 문구: “{d['refrain']['line']}” — " + ", ".join(d["refrain"]["uses"]))
                st.markdown("\n".join(f"  {i}. {a}" for i, a in enumerate(d["story_arc"], 1)))
            with c2:
                if v["judge"]:
                    st.markdown("**채점 근거**")
                    for s in v["judge"]["scores"]:
                        st.markdown(f"- **{s['criterion']} {s['score']}** {s['feedback']}")
            changed = [(a, b) for a, b in zip(v["draft"]["pages"], v["story"]["pages"]) if a["text"] != b["text"]]
            with st.expander(f"다듬기 전후 ({len(changed)}쪽 바뀜)"):
                for a, b in changed:
                    st.markdown(f"**{a['order']}** ~~{a['text']}~~  \n→ {b['text']}")
            with st.expander("설계 JSON"):
                st.json(d, expanded=False)


def render(root: Path):
    if str(root / "evals") not in sys.path:
        sys.path.insert(0, str(root / "evals"))
    base, keys, judge_on, workers, run = _sidebar(root)

    if run:
        with st.status(f"{len(keys)}개 전략 실행 중… (전략마다 1~3분, 동시 {workers}개)", expanded=True) as box:
            def done(k, err):
                box.write(("✗ " if err else "✓ ") + _name(k) + (f" — {err}" if err else ""))
            exp = lab.run_experiment(base, keys, judge_on=judge_on, workers=workers, on_done=done)
            box.update(label="끝", state="complete", expanded=False)
        st.session_state["lab_exp"] = str(exp)

    path = st.session_state.get("lab_exp")
    if not path:
        st.info("왼쪽에서 샘플·기준 실행·전략을 고르고 [실험 시작]. 또는 지난 실험 불러오기.")
        _explain()
        return

    exp_dir = Path(path)
    e = lab.load(exp_dir)
    meta, variants = e["meta"], e["variants"]
    st.header(f"프롬프트 실험 · {exp_dir.name}")
    st.caption(f"기준 {Path(meta['base']).name} · {meta['created']} · 설계·작성 {meta['model_main']} · 채점 {meta['model_judge']}")
    with st.expander("입력과 인터뷰 정리"):
        s = e["context"]["situation"]
        st.markdown(f"**상황** ({s['category']} · {s['timing']}) {s['description']}")
        st.success(e["summary"])
    for k in meta["keys"]:
        if variants[k]["error"]:
            st.error(f"{_name(k)} 실패 — {variants[k]['error']}")
    ok = [k for k in meta["keys"] if variants[k]["story"]]
    if not ok:
        return
    _scores(e, ok)
    _side_by_side(e, ok)
    _detail(e, ok)
    st.caption(f"표·본문 전체: {exp_dir / 'compare.md'}")
