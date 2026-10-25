"""
뷰어 — "어떤 입력이 들어갔을 때 어떤 출력이 나오는지" 눈으로 보는 용도.
    uv run streamlit run viewer/app.py

왼쪽: 입력 (샘플 고르거나 폼 수정) → [실행]
오른쪽: 인터뷰 로그 / Context+summary / 설계 / 동화(그림+질문) / 가이드 / 비용
검토 단계 버튼: [다시 쓰기] [캐릭터 바꾸기] [그림만 다시] [완료]  → parent_review 재개
맨 위 '프롬프트 실험' 화면: 같은 인터뷰로 프롬프트 전략만 바꿔 나란히 비교 (lab_view.py)
버리는 물건. 진짜 프론트는 FE가 만든다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st
from langgraph.types import Command

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from firstory import storage  # noqa: E402
from firstory.graph import compile_graph, new_thread_id  # noqa: E402
from firstory.lab import STRATEGY_LABELS  # noqa: E402
from firstory.schemas import SituationCategory, MessageDirection, Strategy  # noqa: E402

st.set_page_config(page_title="FIRSTORY pipeline", layout="wide")
INPUTS = sorted((ROOT / "datasets" / "inputs").glob("*.json"))

if st.sidebar.radio("화면", ["동화 만들기", "프롬프트 실험"], horizontal=True, label_visibility="collapsed") == "프롬프트 실험":
    import lab_view  # noqa: E402

    lab_view.render(ROOT)
    st.stop()


@st.cache_resource
def graph():
    return compile_graph()


G = graph()


def cfg(tid):
    return {"configurable": {"thread_id": tid}}


def run_until_pause(inp, tid):
    """invoke → interrupt면 멈춤. 결과(state dict)와 interrupt payload 반환."""
    r = G.invoke(inp, cfg(tid))
    pause = r["__interrupt__"][0].value if "__interrupt__" in r else None
    return r, pause


# ─────────────────────────── 왼쪽: 입력 ───────────────────────────
with st.sidebar:
    st.title("FIRSTORY")
    st.caption("AI 파이프라인 프로토타입")

    sample = st.selectbox("샘플", INPUTS, format_func=lambda p: p.stem)
    data = json.loads(sample.read_text(encoding="utf-8"))
    data.pop("_note", None)

    with st.expander("입력 고치기", expanded=False):
        s = data["situation"]
        s["category"] = st.selectbox("상황 카테고리", list(SituationCategory.__args__), index=list(SituationCategory.__args__).index(s["category"]))
        s["timing"] = st.radio("발생 여부", ["past", "upcoming"], index=0 if s["timing"] == "past" else 1, horizontal=True)
        s["description"] = st.text_area("상황 설명", s["description"], height=70)
        c = data["child"]
        c["age_months"] = st.number_input("개월", 36, 96, c["age_months"])
        c["custom_interest"] = st.text_input("관심사 (자유)", c.get("custom_interest") or "")
        data["scripted_answers"] = [a for a in st.text_area(
            "인터뷰 자동 답변 (줄바꿈으로 구분)", "\n".join(data.get("scripted_answers", [])), height=140
        ).splitlines() if a.strip()]

    mode = st.radio("인터뷰", ["자동 (스크립트 답변)", "직접 답하기"], horizontal=False)
    skip_images = st.checkbox("그림 건너뛰기 (텍스트만, 저렴)", value=False)
    strat = st.multiselect("프롬프트 전략 (비우면 지금 방식)", list(STRATEGY_LABELS),
                           format_func=lambda k: STRATEGY_LABELS[k][0],
                           help="\n".join(f"- {n}: {d}" for n, d in STRATEGY_LABELS.values()))

    if st.button("실행", type="primary", width="stretch"):
        tid = new_thread_id()
        answers = data.pop("scripted_answers", [])
        inp = {
            "context": data,
            "run_name": sample.stem,
            "auto_answers": answers if mode.startswith("자동") else [],
            "auto_confirm": mode.startswith("자동"),   # 직접 답하기일 때만 생성 전 확인에서 멈춤
            "auto_approve": False,
            "skip_images": skip_images,
            "strategy": Strategy(**{k: True for k in strat}),
        }
        with st.spinner("생성 중… (이미지 포함 1~3분)"):
            r, pause = run_until_pause(inp, tid)
        st.session_state.update(tid=tid, result=r, pause=pause)

    st.divider()
    st.caption("지난 실행")
    runs = sorted((p for p in (ROOT / "out").glob("20*") if p.is_dir()), reverse=True)[:15]
    picked = st.selectbox("run_dir", ["(선택)"] + [r.name for r in runs])
    if picked != "(선택)" and st.button("불러오기"):
        rd = ROOT / "out" / picked
        loaded = {}
        for name, key in [("00-context.json", "context"), ("01-interview.json", "interview"), ("02-design.json", "story_design"),
                          ("02-strategy.json", "strategy"),
                          ("03-story.json", "story"), ("04-guide.json", "guide"), ("05-illustrations.json", "illustrations"), ("99-cost.json", "cost")]:
            p = rd / name
            if p.exists():
                loaded[key] = json.loads(p.read_text(encoding="utf-8"))
        loaded["run_dir"] = str(rd)
        st.session_state.update(tid=None, result=loaded, pause=None, loaded_json=True)


# ─────────────────────────── 오른쪽: 출력 ───────────────────────────
r = st.session_state.get("result")
pause = st.session_state.get("pause")
tid = st.session_state.get("tid")

if not r:
    st.info("왼쪽에서 샘플 고르고 [실행]. 또는 지난 실행 불러오기.")
    st.stop()


def D(x):
    """pydantic 이든 dict 든 dict 로."""
    if x is None:
        return None
    return x.model_dump() if hasattr(x, "model_dump") else x


ctx = D(r.get("context"))
story = D(r.get("story"))
guide = D(r.get("guide"))
design = D(r.get("story_design"))
ill = D(r.get("illustrations"))
run_dir = Path(r.get("run_dir", ""))
if st.session_state.get("loaded_json"):
    iv = r.get("interview", {})
    turns, summary, done_by = iv.get("turns", []), iv.get("summary"), iv.get("done_by")
    cost = r.get("cost", [])
else:
    turns = [D(t) for t in r.get("interview_turns", [])]
    summary, done_by = r.get("interview_summary"), r.get("interview_done_by")
    cost = [D(c) for c in r.get("cost", [])]

# ── 인터뷰 중 멈춤: 직접 답하기 ──
if pause and pause.get("type") == "interview":
    st.subheader(f"인터뷰 · {pause['turn']}번째 질문")
    st.markdown(f"**FIRSTORY AI** › {pause['question']}")
    ans = st.text_input("부모 답변", key=f"ans{pause['turn']}")
    c1, c2 = st.columns([1, 1])
    if c1.button("답하기", type="primary") and ans.strip():
        with st.spinner("…"):
            r, pause = run_until_pause(Command(resume=ans.strip()), tid)
        st.session_state.update(result=r, pause=pause); st.rerun()
    if c2.button("이만 만들어주세요 (skip)"):
        with st.spinner("생성 중…"):
            r, pause = run_until_pause(Command(resume="skip"), tid)
        st.session_state.update(result=r, pause=pause); st.rerun()
    st.stop()

# ── 생성 전 확인 ──
if pause and pause.get("type") == "confirm":
    st.subheader("이렇게 만들까요?")
    st.caption(f"인터뷰 종료: {pause.get('end_reason')}")
    st.markdown(pause.get("summary") or "(요약 없음)")
    with st.expander("최종 Context"):
        st.json(pause.get("context"))
    if st.button("이대로 만들기", type="primary"):
        with st.spinner("생성 중… (이미지 포함 1~3분)"):
            r, pause = run_until_pause(Command(resume={"action": "generate"}), tid)
        st.session_state.update(result=r, pause=pause); st.rerun()
    st.stop()

# ── 검토 중: 버튼 ──
if pause and pause.get("type") == "review":
    st.subheader("부모 검토")
    b1, b2, b3, b4 = st.columns(4)
    fb = st.text_input("피드백 / 바꿀 방향 / 페이지 번호", placeholder="예: 3페이지 엄마 말이 설명조  ·  토끼 말고 공룡으로  ·  2 5")

    def resume(payload):
        with st.spinner("다시 생성 중…"):
            rr, pp = run_until_pause(Command(resume=payload), tid)
        st.session_state.update(result=rr, pause=pp); st.rerun()

    if b1.button("✓ 완료", type="primary", width="stretch"):
        resume({"action": "approve"})
    if b2.button("다시 쓰기", width="stretch"):
        resume({"action": "regenerate", "scope": "text", "feedback": fb})
    if b3.button("캐릭터/이야기 바꾸기", width="stretch"):
        resume({"action": "regenerate", "scope": "character", "feedback": fb})
    if b4.button("그림만 다시", width="stretch"):
        resume({"action": "regenerate", "scope": "images", "feedback": fb})
    st.divider()

# ── 결과 ──
tab_story, tab_guide, tab_ctx, tab_cost = st.tabs(["동화", "가이드", "인터뷰·Context·설계", "비용"])

with tab_story:
    if not story:
        st.warning("아직 동화 없음")
    else:
        st.header(story["title"])
        imgs = {p["order"]: p for p in (ill or {}).get("pages", [])}
        sheets = (ill or {}).get("character_sheets") or {}
        if sheets:
            with st.expander("캐릭터 시트"):
                cols = st.columns(max(1, len(sheets)))
                for col, c in zip(cols, story.get("characters", [])):
                    pth = sheets.get(c["name"])
                    with col:
                        if pth and storage.exists(pth):
                            st.image(str(storage.local_path(pth)), width=240)
                        st.markdown(f"**{c['name']}** · {c['role']}")
                        st.caption(c["visual_description"])
        q_after = {}
        for q in (guide or {}).get("prompts", []):
            q_after.setdefault(q["after_page"], []).append(q)
        for p in story["pages"]:
            col_img, col_txt = st.columns([1, 1.4])
            pi = imgs.get(p["order"])
            with col_img:
                if pi and pi.get("status") == "completed" and pi.get("path") and storage.exists(pi["path"]):
                    st.image(str(storage.local_path(pi["path"])), width="stretch")
                elif pi and pi.get("status") == "failed":
                    st.error(f"이미지 실패: {pi.get('error', '')[:120]}")
                else:
                    st.caption(f"(이미지 없음) {p['image_prompt']}")
            with col_txt:
                st.markdown(f"**{p['order']}**  {p['text']}")
                st.caption("등장: " + ", ".join(p.get("characters_in_scene", [])))
                for q in q_after.get(p["order"], []):
                    st.info(f"**[{q['purpose']}]** {q['text']}\n\n_{q.get('parent_hint') or ''}_")
        st.caption(f"book.html → {run_dir / 'book.html'}")

with tab_guide:
    if not guide:
        st.warning("아직 가이드 없음")
    else:
        st.subheader("읽기 전에")
        st.write(guide["before_reading"]["intent"])
        for t in guide["before_reading"]["tips"]:
            st.markdown(f"- {t}")
        st.subheader("이야기 속 질문")
        for q in guide["prompts"]:
            st.markdown(f"**p.{q['after_page']} 뒤 · {q['purpose']}** — {q['text']}  \n<span style='color:gray'>{q.get('parent_hint') or ''}</span>", unsafe_allow_html=True)
        st.subheader("다 읽은 뒤")
        st.markdown(f"“{guide['after_reading']['bridge_question']}”")
        if guide["after_reading"].get("if_undecided"):
            st.caption(guide["after_reading"]["if_undecided"])

with tab_ctx:
    st.subheader(f"인터뷰 · {len(turns)}턴 · {done_by}")
    for i, t in enumerate(turns, 1):
        st.markdown(f"**AI** › {t['question']}  \n**부모** › {t['answer']}  \n<span style='color:gray'>{t.get('reason', '')}</span>", unsafe_allow_html=True)
    if summary:
        st.success(summary)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Context (최종)")
        st.json(ctx, expanded=False)
    with c2:
        st.subheader("설계 (간접화)")
        on = [STRATEGY_LABELS[k][0] for k, v in (D(r.get("strategy")) or {}).items() if v]
        st.caption("프롬프트 전략: " + (", ".join(on) if on else "없음 (지금 방식)"))
        st.json(design, expanded=False)

with tab_cost:
    if cost:
        import pandas as pd
        df = pd.DataFrame(cost)
        st.dataframe(df, width="stretch", hide_index=True)
        st.metric("텍스트 토큰 (in / out)", f"{df['input_tokens'].sum()} / {df['output_tokens'].sum()}")
        st.metric("이미지 장수", int(df["images"].sum()))
        st.metric("총 시간(s, 병렬 합산)", f"{df['ms'].sum() / 1000:.1f}")
    else:
        st.caption("비용 정보 없음")
