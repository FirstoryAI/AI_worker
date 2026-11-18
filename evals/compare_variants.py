"""
같은 입력·같은 인터뷰로 설계 방식만 바꿔 동화를 다시 뽑아 나란히 본다. (텍스트만, 이미지 없음)
  uv run python evals/compare_variants.py [--variants c] out/<A 실행 폴더> [...]

A = 기존 실행 결과 (동물·동화적 공간·열린 결말)
C = evals/variants/c/ (동물 주인공·아는 공간·끝나는 사건). 근거: EVIDENCE.md §3
기본 파이프라인은 바꾸지 않는다. 결과는 <A 폴더>__<변형>/ 와 out/compare-<이름>.md
이미 뽑아 둔 변형은 다시 호출하지 않는다 (--force 로 다시 뽑기).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from firstory import llm  # noqa: E402
from firstory.nodes import story as story_node  # noqa: E402
from firstory.schemas import StoryInputContext  # noqa: E402

VARIANTS = Path(__file__).parent / "variants"


# StoryDesign과 필드는 같고 설명만 C에 맞춘 것 (스키마 설명도 모델이 읽는다)
class ProtagonistC(BaseModel):
    name: str = Field(description="아이 이름이 아닌 새 이름. 2~3글자, 발음 쉬운")
    species: str = Field(description="아이 관심사에서 끌어온 동물. 옷을 입고 아이처럼 생활한다")
    traits: list[str]


class SupportingC(BaseModel):
    name: str
    species: str = Field(description="주인공과 한눈에 구분되는 다른 동물")
    role: str = Field(description="주인공과의 관계. 예: 같은 반 친구, 엄마, 선생님")
    traits: list[str]


class StoryDesignC(BaseModel):
    protagonist: ProtagonistC
    supporting: Optional[SupportingC] = Field(None, description="이야기에 가장 필요한 한 명. 꼭 없어도 되면 null")
    world: str = Field(description="아이가 아는 일상 공간 (동물 아이들의 유치원·놀이터·집). 지어낸 지명·환상 요소 없이")
    mirrored_situation: str = Field(description="감정 구조는 같고 겉의 디테일은 바꾼, 비슷한 일을 겪는 동물 아이의 상황")
    values_to_honor: list[str] = Field(description="이야기 안에 자연스럽게 있되 결론으로 주입하지 않을 가치")
    story_arc: list[str] = Field(description="페이지 흐름 요약 (배경→발단→감정→주인공의 시도→결과→반응)")


SCHEMAS = {"c": StoryDesignC}
LABELS = {"c": "C. 동물·아는 공간·끝나는 사건"}


def _read(d: Path, name: str):
    return json.loads((d / name).read_text(encoding="utf-8"))


def run_variant(a_dir: Path, v: str, force: bool = False) -> Path:
    v_dir = a_dir.with_name(f"{a_dir.name}__{v.upper()}")
    if not force and (v_dir / "04-guide.json").exists():
        return v_dir
    state = {
        "context": StoryInputContext(**_read(a_dir, "00-context.json")),
        "interview_summary": _read(a_dir, "01-interview.json").get("summary") or "",
    }

    prompts, design_schema = llm._PROMPTS, story_node.StoryDesign
    llm._PROMPTS, story_node.StoryDesign = VARIANTS / v, SCHEMAS[v]
    try:
        state.update(story_node.design_story(state))
        state.update(story_node.write_story(state))
    finally:
        llm._PROMPTS, story_node.StoryDesign = prompts, design_schema
    state.update(story_node.reading_guide(state))  # 가이드 프롬프트는 A와 동일

    v_dir.mkdir(exist_ok=True)
    for name, key in (("02-design.json", "story_design"), ("03-story.json", "story"), ("04-guide.json", "guide")):
        (v_dir / name).write_text(json.dumps(state[key].model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return v_dir


def _load(d: Path) -> dict:
    return {"design": _read(d, "02-design.json"), "story": _read(d, "03-story.json"), "guide": _read(d, "04-guide.json")}


def _cell(s) -> str:
    return str(s).replace("\n", " ").replace("|", "\\|")


def _who(d: dict) -> str:
    who = f"{d['protagonist']['name']} ({d['protagonist']['species']})"
    if d.get("supporting"):
        s = d["supporting"]
        who += f" · {s['name']} ({s['species']}, {s['role']})"
    return who


def _guide_questions(guide: dict) -> str:
    return "<br>".join(f"({q['after_page']}쪽 뒤) {_cell(q['text'])}" for q in guide["prompts"])


def compare_md(a_dir: Path, dirs: dict[str, Path]) -> str:
    cols = [("A. 지금 방식", _load(a_dir))] + [(LABELS[v], _load(d)) for v, d in dirs.items()]

    def row(head: str, f) -> str:
        return f"| {head} | " + " | ".join(f(x) for _, x in cols) + " |"

    out = [f"# {a_dir.name.split('_', 1)[-1]}: " + " vs ".join(n.split(".")[0] for n, _ in cols), "",
           "| | " + " | ".join(n for n, _ in cols) + " |", "|---" * (len(cols) + 1) + "|",
           row("제목", lambda x: _cell(x["story"]["title"])),
           row("인물", lambda x: _cell(_who(x["design"]))),
           row("배경", lambda x: _cell(x["design"]["world"]))]
    pages = [{p["order"]: p["text"] for p in x["story"]["pages"]} for _, x in cols]
    for o in sorted(set().union(*pages)):
        out.append(f"| {o}쪽 | " + " | ".join(_cell(p.get(o, "")) for p in pages) + " |")
    out += [row("가이드 질문", lambda x: _guide_questions(x["guide"])),
            row("연결 질문", lambda x: _cell(x["guide"]["after_reading"].get("bridge_question", ""))), ""]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--variants", nargs="+", choices=sorted(SCHEMAS), default=sorted(SCHEMAS))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    for a_dir in args.runs:
        dirs = {v: run_variant(a_dir, v, args.force) for v in args.variants}
        md = a_dir.parent / f"compare-{a_dir.name.split('_', 1)[-1]}.md"
        md.write_text(compare_md(a_dir, dirs), encoding="utf-8")
        print("→", md)


if __name__ == "__main__":
    main()
