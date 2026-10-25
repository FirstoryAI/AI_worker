"""
프롬프트 실험 — 같은 입력·같은 인터뷰로 프롬프트 전략만 바꿔 동화(텍스트)를 뽑고, 채점해서 나란히 본다.
뷰어 '프롬프트 실험' 화면과 evals/prompt_lab.py 가 이 모듈을 쓴다.

결과: out/lab/<시각>_<샘플>/
  meta.json · 00-context.json · 01-interview.json (기준 실행에서 복사) · compare.md
  <전략>/ 02-strategy.json 02-design.json 03-draft.json 03-story.json 06-judge.json 99-cost.json
"""
from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from langgraph.graph import END, START, StateGraph

from .config import config
from .llm import prompt, structured
from .nodes.story import (
    _age, _persona, design_story, polish_story, write_story,
)
from .schemas import CostEntry, StoryInputContext, StoryJudgement, Strategy
from .state import PipelineState

LAB = config.out_dir / "lab"

STRATEGY_LABELS = {
    "arc": ("상황별 흐름", "상황 카테고리마다 다른 감정 흐름 템플릿 (용기 쌓기, 다시 같이 놀기 …). prompts/arcs/"),
    "engine": ("이야기 엔진", "원하는 것 → 시도 3번(1·2번은 실패) → 그 뒤로. Story Spine"),
    "fewshot": ("설계 예시", "좋은 설계 예시 하나를 보여 준다. Dramatron"),
    "motif": ("반복·위로 물건", "마음만 바뀌며 돌아오는 말 + 해결에 쓰이는 실제 물건. StoryTale"),
}
# 실험 한 칸 = 전략 조합 하나. 키는 폴더 이름이 된다.
PRESETS: dict[str, tuple[str, str, Strategy]] = {
    "base": ("기본", "지금 프롬프트 그대로", Strategy()),
    **{k: (name, desc, Strategy(**{k: True})) for k, (name, desc) in STRATEGY_LABELS.items()},
    "all": ("전부", "네 전략을 모두 켠다", Strategy(**{k: True for k in STRATEGY_LABELS})),
}


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _w(p: Path, obj):
    data = obj.model_dump() if hasattr(obj, "model_dump") else obj
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _text_graph():
    """설계 → 쓰기 → 다듬기. 본 그래프와 같은 노드, 인터뷰·그림·가이드만 뺐다."""
    g = StateGraph(PipelineState)
    for name, fn in [("design_story", design_story), ("write_story", write_story), ("polish_story", polish_story)]:
        g.add_node(name, fn)
    g.add_edge(START, "design_story")
    g.add_edge("design_story", "write_story")
    g.add_edge("write_story", "polish_story")
    g.add_edge("polish_story", END)
    return g.compile()


def judge(ctx: StoryInputContext, summary: str, arc: list[str], pages: list[dict]) -> tuple[StoryJudgement, CostEntry]:
    """재미·개연성·따뜻함·눈높이·부모 의도·주인공 주도 1~5점 + 설계 항목이 본문에 일어났는지."""
    years, _ = _age(ctx)
    return structured(
        node="story_judge",
        model=config.model_judge,
        schema=StoryJudgement,
        system=prompt("story_judge", persona=_persona, summary=summary, arc=arc,
                      pages=[{"order": p["order"], "text": p["text"]} for p in pages], age_years=years),
        user="채점하세요.",
        reasoning="low",
    )


def run_variant(exp: Path, key: str, judge_on: bool = True) -> Path:
    """실험 폴더의 기준 입력으로 전략 하나를 돌린다."""
    _, _, strategy = PRESETS[key]
    ctx = StoryInputContext(**_j(exp / "00-context.json"))
    summary = (_j(exp / "01-interview.json") or {}).get("summary") or ""
    s = _text_graph().invoke({"context": ctx, "interview_summary": summary, "strategy": strategy, "cost": []})

    d = exp / key
    d.mkdir(exist_ok=True)
    _w(d / "02-strategy.json", strategy)
    _w(d / "02-design.json", s["story_design"])
    _w(d / "03-draft.json", s["story_draft"])
    _w(d / "03-story.json", s["story"])
    cost = list(s["cost"])
    if judge_on:
        story = s["story"].model_dump()
        jg, c = judge(ctx, summary, s["story_design"].story_arc, story["pages"])
        _w(d / "06-judge.json", jg)
        cost.append(c)
    _w(d / "99-cost.json", [c.model_dump() for c in cost])
    return d


def new_experiment(base: Path, keys: list[str], judge_on: bool = True, root: Path = LAB) -> Path:
    """기준 실행 폴더(00-context·01-interview가 있는)에서 실험 폴더를 만든다."""
    exp = root / f"{datetime.now():%Y%m%d-%H%M%S}_{base.name.split('_', 1)[-1]}"
    exp.mkdir(parents=True)
    for name in ("00-context.json", "01-interview.json"):
        shutil.copy(base / name, exp / name)
    _w(exp / "meta.json", {
        "base": str(base), "keys": keys, "judge": judge_on, "created": datetime.now().isoformat(timespec="seconds"),
        "page_count": config.page_count, "model_main": config.model_main, "model_judge": config.model_judge,
    })
    return exp


def run_experiment(base: Path, keys: list[str], judge_on: bool = True, workers: int = 3, root: Path = LAB,
                   on_done: Optional[Callable[[str, Optional[str]], None]] = None) -> Path:
    """전략마다 동시에 돌린다. on_done(키, 오류)는 이 함수를 부른 스레드에서 불린다 (뷰어 진행 표시용)."""
    exp = new_experiment(base, keys, judge_on, root)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(run_variant, exp, k, judge_on): k for k in keys}
        for f in as_completed(futs):
            k, err = futs[f], None
            try:
                f.result()
            except Exception as e:  # 한 전략이 실패해도 나머지는 본다
                err = f"{type(e).__name__}: {e}"
                (exp / k).mkdir(exist_ok=True)
                (exp / k / "error.txt").write_text(err, encoding="utf-8")
            if on_done:
                on_done(k, err)
    (exp / "compare.md").write_text(compare_md(exp), encoding="utf-8")
    return exp


def make_base(sample: Path) -> Path:
    """샘플 입력으로 기준 실행을 하나 만든다 (스크립트 답변으로 인터뷰, 그림 없이, 검토 자동 완료)."""
    from .graph import compile_graph, new_thread_id

    data = json.loads(sample.read_text(encoding="utf-8"))
    data.pop("_note", None)
    answers = data.pop("scripted_answers", [])
    r = compile_graph().invoke(
        {"context": data, "run_name": sample.stem, "auto_answers": answers, "auto_confirm": True, "auto_approve": True,
         "skip_images": True},
        {"configurable": {"thread_id": new_thread_id()}},
    )
    return Path(r["run_dir"])


def base_runs(sample_stem: Optional[str] = None) -> list[Path]:
    """기준으로 쓸 수 있는 실행 폴더 (인터뷰 정리가 있는 것), 최신순."""
    runs = [p for p in config.out_dir.glob("20*") if p.is_dir() and "__" not in p.name
            and (p / "00-context.json").exists() and (p / "01-interview.json").exists()]
    if sample_stem:
        runs = [p for p in runs if p.name.split("_", 1)[-1] == sample_stem]
    return sorted(runs, reverse=True)


def experiments(root: Path = LAB) -> list[Path]:
    return sorted((p for p in root.glob("20*") if (p / "meta.json").exists()), reverse=True) if root.exists() else []


def load(exp: Path) -> dict:
    meta = _j(exp / "meta.json")
    variants = {}
    for k in meta["keys"]:
        d = exp / k
        err = (d / "error.txt").read_text(encoding="utf-8") if (d / "error.txt").exists() else None
        variants[k] = {
            "dir": d, "error": err, "design": _j(d / "02-design.json"),
            "draft": _j(d / "03-draft.json"), "story": _j(d / "03-story.json"), "judge": _j(d / "06-judge.json"),
            "cost": _j(d / "99-cost.json") or [],
        }
    return {"dir": exp, "meta": meta, "context": _j(exp / "00-context.json"),
            "summary": (_j(exp / "01-interview.json") or {}).get("summary") or "", "variants": variants}


def score_row(v: dict) -> dict:
    """점수표 한 줄. 채점·비용이 없으면 비워 둔다."""
    row: dict = {}
    jg = v.get("judge")
    if jg:
        for s in jg["scores"]:
            row[s["criterion"]] = s["score"]
        vals = [s["score"] for s in jg["scores"]]
        row["평균"] = round(sum(vals) / len(vals), 2) if vals else None
        af = jg.get("arc_followed") or []
        row["설계 반영"] = f"{sum(af)}/{len(af)}" if af else None
    cost = v.get("cost") or []
    if cost:
        row["토큰"] = sum(c["input_tokens"] + c["output_tokens"] for c in cost)
        row["시간(s)"] = round(sum(c["ms"] for c in cost) / 1000)
    return row


def compare_md(exp: Path) -> str:
    e = load(exp)
    keys = [k for k in e["meta"]["keys"] if e["variants"][k]["story"]]
    cell = lambda s: str(s).replace("\n", " ").replace("|", "\\|")
    name = lambda k: PRESETS[k][0]
    out = [f"# 프롬프트 실험 · {exp.name}", "", f"기준: `{e['meta']['base']}`", "",
           f"> {cell(e['summary'])}", ""]
    rows = {k: score_row(e["variants"][k]) for k in keys}
    cols = [c for c in ["재미", "개연성", "따뜻함", "눈높이", "부모 의도", "주인공 주도", "평균", "설계 반영", "토큰", "시간(s)"]
            if any(c in r for r in rows.values())]
    out += ["| 전략 | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    out += [f"| {name(k)} | " + " | ".join(cell(rows[k].get(c, "")) for c in cols) + " |" for k in keys]
    out += ["", "| | " + " | ".join(name(k) for k in keys) + " |", "|---" * (len(keys) + 1) + "|",
            "| 제목 | " + " | ".join(cell(e["variants"][k]["story"]["title"]) for k in keys) + " |"]
    pages = [{p["order"]: p["text"] for p in e["variants"][k]["story"]["pages"]} for k in keys]
    for o in sorted(set().union(*pages)):
        out.append(f"| {o}쪽 | " + " | ".join(cell(p.get(o, "")) for p in pages) + " |")
    failed = [k for k in e["meta"]["keys"] if e["variants"][k]["error"]]
    if failed:
        out += ["", "실패: " + ", ".join(f"{name(k)} ({e['variants'][k]['error'][:80]})" for k in failed)]
    return "\n".join(out) + "\n"
