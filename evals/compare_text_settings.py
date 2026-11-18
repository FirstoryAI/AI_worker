"""
설계(design_story)·독서 가이드(reading_guide)의 설정만 바꿔 같은 입력으로 다시 뽑아 나란히 본다.
  uv run python evals/compare_text_settings.py --reasoning low out/<실행 폴더> [...]
  uv run python evals/compare_text_settings.py --design-model light out/<실행 폴더> [...]

기준(지금 설정)과 변형을 둘 다 새로 호출해 토큰·시간을 같은 조건에서 잰다.
가이드는 두 쪽 모두 실행 폴더의 기존 동화(03-story.json)에 대해 만든다.
결과: out/compare-<라벨>-<이름>.md · LangSmith에는 태그 compare:<라벨>:(base|variant)
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firstory.config import config  # noqa: E402
from firstory.nodes import story as story_node  # noqa: E402
from firstory.schemas import StoryInputContext, StoryText  # noqa: E402

_structured = story_node.structured


@contextlib.contextmanager
def tagged(tag: str):
    try:
        from langsmith import trace
    except ImportError:
        yield
        return
    with trace(name=tag, tags=[tag]):
        yield


def _read(a_dir: Path, name: str):
    return json.loads((a_dir / name).read_text(encoding="utf-8"))


def run(a_dir: Path, *, reasoning: str | None, design_model: str | None, tag: str):
    def patched(**kw):
        if reasoning and kw["node"] in ("design_story", "reading_guide"):
            kw["reasoning"] = reasoning
        if design_model and kw["node"] == "design_story":
            kw["model"] = design_model
        return _structured(**kw)

    state = {
        "context": StoryInputContext(**_read(a_dir, "00-context.json")),
        "interview_summary": _read(a_dir, "01-interview.json").get("summary") or "",
        "story": StoryText(**_read(a_dir, "03-story.json")),
    }
    story_node.structured = patched
    try:
        with tagged(tag):
            d = story_node.design_story(state)
            g = story_node.reading_guide(state)
    finally:
        story_node.structured = _structured
    return d["story_design"].model_dump(), g["guide"].model_dump(), {c.node: c for c in d["cost"] + g["cost"]}


def _cell(s) -> str:
    return str(s).replace("\n", " ").replace("|", "\\|")


def _who(d: dict) -> str:
    who = f"{d['protagonist']['name']} ({d['protagonist']['species']})"
    if d.get("supporting"):
        s = d["supporting"]
        who += f" · {s['name']} ({s['species']}, {s['role']})"
    return who


def _arc_step(d: dict, i: int) -> str:
    return _cell(d["story_arc"][i]) if i < len(d["story_arc"]) else ""


def _guide_prompt(g: dict, i: int) -> str:
    if i >= len(g["prompts"]):
        return ""
    q = g["prompts"][i]
    return f"({q['after_page']}쪽 뒤, {q['purpose']}) {_cell(q['text'])}<br>부모 힌트: {_cell(q.get('parent_hint') or '')}"


def md(name, label, base, var) -> str:
    (db, gb, cb), (dv, gv, cv) = base, var
    out = [f"# {name}: 기준 vs {label}", "", "## 토큰·시간", "", "| 노드 | | 기준 | 변형 |", "|---|---|---|---|"]
    for node in ("design_story", "reading_guide"):
        b, v = cb[node], cv[node]
        out += [f"| {node} | 모델 | {b.model} | {v.model} |", f"| | 입력 토큰 | {b.input_tokens} | {v.input_tokens} |",
                f"| | 출력 토큰 | {b.output_tokens} | {v.output_tokens} |", f"| | 시간 | {b.ms / 1000:.1f}s | {v.ms / 1000:.1f}s |"]
    out += ["", "## 설계", "", "| | 기준 | 변형 |", "|---|---|---|",
            f"| 인물 | {_cell(_who(db))} | {_cell(_who(dv))} |", f"| 배경 | {_cell(db['world'])} | {_cell(dv['world'])} |",
            f"| 상황 | {_cell(db['mirrored_situation'])} | {_cell(dv['mirrored_situation'])} |",
            f"| 가치 | {_cell(' / '.join(db['values_to_honor']))} | {_cell(' / '.join(dv['values_to_honor']))} |"]
    for i in range(max(len(db["story_arc"]), len(dv["story_arc"]))):
        out.append(f"| 흐름 {i + 1} | {_arc_step(db, i)} | {_arc_step(dv, i)} |")
    out += ["", "## 독서 가이드 (같은 동화에 대해)", "", "| | 기준 | 변형 |", "|---|---|---|",
            f"| 방향 | {_cell(gb['before_reading']['intent'])} | {_cell(gv['before_reading']['intent'])} |",
            f"| 팁 | {_cell(' / '.join(gb['before_reading']['tips']))} | {_cell(' / '.join(gv['before_reading']['tips']))} |"]
    for i in range(max(len(gb["prompts"]), len(gv["prompts"]))):
        out.append(f"| 질문 {i + 1} | {_guide_prompt(gb, i)} | {_guide_prompt(gv, i)} |")
    out += [f"| 연결 질문 | {_cell(gb['after_reading']['bridge_question'])} | {_cell(gv['after_reading']['bridge_question'])} |", ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--reasoning", choices=["minimal", "low", "medium", "high"])
    ap.add_argument("--design-model", choices=["light", "main"])
    args = ap.parse_args()
    model = {"light": config.model_light, "main": config.model_main}.get(args.design_model)
    parts = []
    if args.reasoning:
        parts.append(f"reasoning-{args.reasoning}")
    if model:
        parts.append(f"design-{args.design_model}")
    label = "-".join(parts)
    for a_dir in args.runs:
        name = a_dir.name.split("_", 1)[-1]
        base = run(a_dir, reasoning=None, design_model=None, tag=f"compare:{label}:base")
        var = run(a_dir, reasoning=args.reasoning, design_model=model, tag=f"compare:{label}:variant")
        dest = a_dir.parent / f"compare-{label}-{name}.md"
        dest.write_text(md(name, label, base, var), encoding="utf-8")
        print("→", dest)


if __name__ == "__main__":
    main()
